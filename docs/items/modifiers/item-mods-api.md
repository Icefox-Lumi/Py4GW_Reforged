# 10 — `Item.Mods` API (the mod read/filter layer)

The clean, game-sourced mod-read/filter layer that the whole RE effort was building toward.
Self-contained, reads the raw `ItemModifier` words directly, and **does not** depend on the
(deprecated, deleted) `Item.Customization.Modifiers` or the old `item_mods_src` parser.

> **This doc matches the live code** (`Py4GWCoreLib/Item.py` → `Item.Mods`, backed by
> `Py4GWCoreLib/mods_core.py` + `Py4GWCoreLib/mods_types.py`). Earlier drafts of this file
> described a `Has/HasAll/GetAll` API, a `Mod` value object, and `mod_ids.py` /
> `mods_value_args.py` — **none of those exist**. If you see them referenced anywhere, they are
> stale. The names below are the real ones.

## The API — `Py4GWCoreLib/Item.py`

Identifiers come from `ModifierIdentifier` (aliased `ModId`) in `Py4GWCoreLib/mods_types.py`.
The value axis is **type-routed**: an `IntEnum` narrows the *subtype*, and a
number is one direction-aware threshold (see below). Callable predicates and
two-number/range-shaped input are not accepted.

```python
# -- presence / matching --
Item.Mods.HasMod(item_id, mod, *values)   -> bool   # mod present, optionally value/subtype-filtered
Item.Mods.HasEffect(item_id, criterion)   -> bool   # typed effect criterion; selects one effect-value component
Item.Mods.HasAllMods(item_id, modlist)    -> bool   # every entry matches
Item.Mods.HasAnyMods(item_id, modlist)    -> bool   # any entry matches
#   modlist entry = mod | (mod, *values) | EffectCriterion(...)
Item.Mods.HasUpgrade(item_id, criterion)  -> bool   # typed installed-upgrade identity/slot/value criterion
Item.Mods.GetMatchingUpgrades(item_id, criterion) -> tuple[UpgradeFact] # typed installed-upgrade facts satisfying it
Item.Mods.HasAllUpgrades(item_id, rules)  -> bool   # every UpgradeCriterion matches
Item.Mods.HasAnyUpgrades(item_id, rules)  -> bool   # any UpgradeCriterion matches

# -- reads --
Item.Mods.GetMods(item_id)                -> list[ModId]      # distinct mod ids present
Item.Mods.GetValues(item_id, mod)         -> list[int]        # value(s) of first match ([] if none)
Item.Mods.GetSubtype(item_id, mod)        -> IntEnum | None   # attribute / damage type / species …
Item.Mods.GetRaw(item_id, mod)            -> (arg1, arg2) | None
Item.Mods.GetName(mod)                    -> str              # the mod's effect/base name

# -- applied upgrades (prefixes/suffixes/inscriptions/runes/insignias) --
Item.Mods.GetUpgrades(item_id)            -> list[(name, Slot)]
Item.Mods.GetKnownUpgrades()               -> list[(name, Slot)] # supported configuration choices
Item.Mods.Inspect(item_id)                 -> ItemInspection     # typed effects + installed upgrade facts
Item.Mods.GetKnownUpgradeFacts()           -> tuple[UpgradeFact] # typed core-owned upgrade catalog
Item.Mods.NormalizeUpgradeIdentifier(value)-> str | None         # persisted display name -> stable identity
Item.Mods.ResolveUpgradeSlot(value)        -> Slot | None        # persisted slot name/value -> public slot
Item.Mods.CreateUpgradeCriterion(identifier, *, slot=None, threshold=None, value_index=0)
                                                    -> UpgradeCriterion # typed N-or-better query
Item.Mods.GetUpgradeInSlot(item_id, slot) -> str | None
Item.Mods.HasUpgradeInSlot(item_id, slot) -> bool
Item.Mods.GetSlot(item_id, upgrade_name)  -> Slot | None
Item.Mods.IsMaxed(item_id, upgrade_name)  -> bool

# -- raw modifier words (diagnostics and legacy compatibility only) --
Item.Mods.GetModifiers(item_id)           -> list[ItemModifier]
Item.Mods.GetModifierCount(item_id)       -> int
Item.Mods.ModifierExists(item_id, ident)  -> bool
Item.Mods.GetModifierValues(item_id, ident) -> (arg, arg1, arg2)
```

`Slot` (from `mods_core`): `Inherent, Prefix, Suffix, Inscription, Rune, Insignia`.

`ItemInspection.effects` contains `EffectFact(identifier, name, values, subtype,
better_is_lower)`. `ItemInspection.upgrades` contains
`UpgradeFact(identifier, display_name, slot, values, is_maxed)`. Those immutable facts are the public
surface for rule consumers such as Merchant Rules: identities, slots, and
threshold direction are available without a raw triple, JSON catalog, or
consumer-owned parser. `NormalizeUpgradeIdentifier` accepts an old
display-style persisted name only to resolve it to the stable Reforged identity.
The catalog has no upper-range or exact-match mode.

`EffectCriterion(identifier, threshold=None, value_index=0, subtype=None)`
is the declarative form for one specific effect-value component. Its threshold
is always match-or-better and it takes its comparison direction from the
matching `EffectFact`. This is how a consumer requests the displayed high
damage component: there is no callable predicate, raw modifier triple, or
consumer-owned range comparison.

`CreateUpgradeCriterion(identifier, slot=..., threshold=...)` constructs the
public query for `GetMatchingUpgrades`; it normalizes persisted identities and
slots and rejects unknown non-empty values rather than widening a rule.
`GetMatchingUpgrades(item_id, UpgradeCriterion(...))` is the typed companion
to `HasUpgrade`. A consumer that needs a matching fact's display name, slot,
or values after Reforged has made the match uses this result; it must not
rebuild the comparison from cached tuples. `HasUpgrade` is the boolean form of
the same owner operation.

### Value routing in `HasMod(item_id, mod, *values)`

Each extra arg is dispatched by its Python type:

- **`IntEnum`** → subtype filter (e.g. `Attribute.Marksmanship`, `DamageType.Piercing`).
- **one number** → **"that value or better"**, not exact. Direction is the *mod's* metadata
  (`better_low`): requirement is lower-is-better (`9` ⇒ req ≤ 9); damage/armor/health are
  higher-is-better (`15` ⇒ ≥ 15). More than one numeric value is rejected;
  select a specific effect component with `EffectCriterion(value_index=...)`.
  No per-call parameter or lambda is needed.
- **callable** → rejected. `Item.Mods` accepts declarative subtype and numeric
  threshold values only.

### Usage

```python
from Py4GWCoreLib.Item import Item
from Py4GWCoreLib.mods_types import ModifierIdentifier as ModId
from Py4GWCoreLib.enums_src.GameData_enums import Attribute, DamageType

Item.Mods.HasMod(item_id, ModId.AttributeRequirement, Attribute.Marksmanship, 9)  # Marks req ≤ 9
Item.Mods.HasEffect(item_id, Item.Mods.EffectCriterion(ModId.Damage, 28, 1))      # damage high end ≥ 28
Item.Mods.HasAllMods(item_id, [
    ModId.DamageTypeProperty,                       # present (any)
    (ModId.AttributeRequirement, 9),                # req 9 or better
    Item.Mods.EffectCriterion(ModId.Damage, 28, 1), # damage high end 28 or better
])
Item.Mods.HasUpgrade(
    item_id,
    Item.Mods.CreateUpgradeCriterion("Icy", slot="Prefix", threshold=15),
)
vals = Item.Mods.GetValues(item_id, ModId.Damage)   # e.g. [15, 28]
```

## Why the value arg varies — and where it comes from (RE)

A mod word is `identifier(16) + arg1(8) + arg2(8)`, but **which arg holds the value varies per
identifier** — arg2 for most, arg1 for some, both for compound (subtype-carrying) mods. This is not
a formula: the game's `CNameComposer::ProcessCodes` (~118 KB, `0x80a7ecdb`–`0x80a9baac`) is a
per-identifier code dispatch, and handlers like `ProcessAttribute` (`0x80a7e5a0`) even use
non-byte-aligned bit extraction (`value = (code>>1)&0xFFFF` + flag bits). There is **no static
value-arg table** in the binary.

**We derive it from the game itself, not from a JSON.** The per-identifier read rule
(value arg, subtype enum, better-direction) is declared in the `_Def` table inside
`Py4GWCoreLib/mods_core.py` — matched against the numbers the game *displays*. `value_of`,
`subtype_of`, and `is_better` read that table; `Item.Mods` calls them.

- **Confidence:** the value/threshold axis is solid (from displayed numbers). The subtype axis
  (which arg holds the enum for a few damage-type/species/condition mods) may need targeted
  handler RE to be 100% — see docs 06/09.

## Live layout

| File | What |
|---|---|
| `Py4GWCoreLib/Item.py` (`Item.Mods`) | the public API above |
| `Py4GWCoreLib/mods_core.py` | the one decoder + `_Def` read-rule table + `Slot`; `decode_item`, `find`, `value_of`, `subtype_of`, `is_better`, `upgrades_on`, `describe_item`, `raw_dump` |
| `Py4GWCoreLib/mods_types.py` | `ModifierIdentifier` (`ModId`) — the identifier constants (~548 entries) |
| `docs/items/modifiers/game-mod-table.md` | provenance and verification record for the game-derived mod list |

## Validate before building on it

`Widgets/Coding/Debug/Py4GW/Item Mods Playground.py` latches a hovered item,
compares public descriptions with the game tooltip, and exercises directional
ALL/ANY and threshold helpers. `Widgets/Coding/Debug/Py4GW/Mod Parity Scan.py`
writes the broader game-versus-Reforged report. If a row is off, fix the
owner's `_Def` in `mods_core.py`; do not give a consumer a raw fallback.

## Regenerating
- The `_Def` read rules and `ModifierIdentifier` derive from the Ghidra dump
  and native composer binding. Re-run the owner-approved extraction workflow
  after a game patch; keep only the resulting conclusion in this record.
