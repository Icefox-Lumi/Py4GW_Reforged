# LEGACY — superseded, not the basis for the new class

Everything in this folder is **historical**. The loot class is being constructed fresh, guided by the
owner; these documents are **not** the design and must not be treated as decisions.

Why they were retired: they accumulated inferred design, reframed decisions the owner had already
settled, and were written before the system was properly understood. An implementation built from them
was reverted.

**What is still worth reading here — facts, not design:**

- `how-it-works-today.md` — a line-cited audit of the *existing* system, corroborated against the
  code. Useful as reference for how things work today; every claim carries a `file:line`. Note it also
  records where earlier versions of these docs were **wrong** (marked `[was wrong]`).
- `grouping.json` / `grouping-review.json` — the merged category → subgroup → model-id data extracted
  from the two legacy catalogs (with the 5 misspellings fixed). Data, not design.
- `salvage-mapping.json` / `salvage-mapping-review.json` — `item model id → {common, rare}` material
  ids, extracted from frenkey's scraped `items.json`. Data, not design.
- `dropinfo.json` — the old "Dropped from …" strings. Retained only for reference; the owner has
  decided this field is **not** carried forward.

**What to ignore here:** `index.md`, `loot-redesign.md`, `structure-and-build.md` as design
authorities. They contain proposals, structures and build orders that are superseded.

The new work lives in the parent folder.
