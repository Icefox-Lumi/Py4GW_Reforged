# Map Overlay Merge — Feature Inventory (Union)

> Purpose: the complete set of features from **both** widgets, so the fresh core can be
> checked against it and nothing is silently dropped. Source column: **C** = Compass +,
> **M** = Mission Map +, **C+M** = both (often implemented differently).
> "Keep?" is a *proposal* for the design phase, not a final decision.

## Legend
- Source: which widget has it today.
- Frame: which frame it naturally belongs to — `compass`, `mission`, or `both`.

## Markers & shapes

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Shape set: Circle, Tear, Square | C+M | both | Keep — common baseline |
| Extra shapes: Triangle, Teardrop, Penta, SignPost, Lock, Scale | M | both | Keep — richer set from Mission Map registry |
| Extra shapes: Star, Tear2 (arc-based teardrop) | C | both | Keep — Compass-only variants; fold into registry |
| Per-shape rotation by `offset_angle` (agent facing) | C+M | both | Keep — must work under map rotation too |
| Whole-map rotation applied to all shapes | C | compass | Keep — required for compass |
| Accent/outline color per marker | C+M | both | Keep |
| Shape-instance cache + color→int cache (perf) | M | both | Keep as core mechanism |
| Target highlight (yellow accent + size bump) | C+M | both | Keep — unify (`_get_alternate_color` / `line_col`) |
| Boss glow: enlarged + profession color | C | both | Keep |

## Agent classification

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Player, Ally(player), Ally(NPC), Players, Neutral, Enemy | C+M | both | Keep |
| Pet vs Enemy-pet (model-id / unspawned) | C+M | both | Keep |
| Minion | C+M | both | Keep |
| Spirit detection (ranger/rit/vanguard) | C+M | both | Keep — unify into one spirit table |
| Ritualist spirit sub-ranges: spirit/longbow(1350)/earshot/area | C | both | Keep — Compass has the finer taxonomy |
| Spirit aura ring (range-colored fill) | C+M | both | Keep — Mission Map draws for pet+enemy spirits |
| Spirit range alpha slider | C | both | Keep |
| NPC vs Minipet (level > 1) | C+M | both | Keep |
| Quest NPC → Star marker | C | both | Keep |
| Merchant detection (name contains MERCHANT) → Scale | M | both | Keep |
| Gadget vs Chest (gadget-id set) | M | both | Keep — Mission Map has chest ids |
| Signpost/gadget marker | C+M | both | Keep |
| Items by rarity (white/blue/purple/gold/green) | C+M | both | Keep |
| Distance culling (`culling` range) | C | both | Keep — Compass-only; useful for compass perf |
| Custom markers by model-id (+ "Get from Target") | C | both | Keep — Compass-only, popular feature |

## Rings, bubbles, ranges

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Configurable range-ring list (Touch…Compass) + editor | C | compass | Keep — **Compass feature**, distinct from player ranges below |
| Ring fill color + outline color + thickness per ring | C | compass | Keep |
| Aggro bubble (Earshot): 4px stroke inset 2px **+** fill | M | mission | Keep — **Mission-exclusive**, bespoke rendering (not a ring) |
| Compass-range indicator: black hairline at exact compass radius **+** band inset `2.85·zoom`, thickness `5.7·zoom` | M | mission | Keep — **Mission-exclusive** and zoom-tailored. NOT interchangeable with the Compass "Compass" ring |
| Adaptive circle segment count by radius | M | both | Keep — perf detail |

## Terrain / pathing render (DXOverlay)

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Pathing trapezoid geometry render | C+M | both | Keep |
| Invert rendering toggle | C+M | both | Keep |
| Circular mask (radius = culling) | C | compass | Keep for compass |
| Rectangular mask (map frame bounds) | M | mission | Keep for mission |
| Terrain color config | M | both | Keep |
| Mega-zoom fill color + mega-zoom render path | M | mission | Keep (mission-only) |
| Per-map geometry-built cache | M | both | Keep — perf |
| Pathing visible toggle | C+M | both | Keep |

## Projection / transform

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Rotation-aware game↔screen | C | compass | Keep — via native `MiniMap.MapProjection` |
| Axis-aligned game↔screen | M | mission | Keep — via `MissionMap.MapProjection` |
| Mega-zoom offset added to base zoom | M | mission | Keep |
| Transform params fetched once/frame + cached | M | both | Keep — apply to both frames |
| gwinch→pixels helper (ring radii) | M | both | Keep |
| Per-map boundary/world-bounds cache | M | both | Keep |

## Interaction

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Click marker → change target | C | both | Keep |
| Alt-click → move to point | C | both | Keep (simple movement mode) |
| Left-click → capture last coords + Copy button | M | mission | Keep |
| Right-click → NavMesh snap-to-nearest-reachable move | M | both? | Keep — decide if compass frame allows it |
| Shift-right-click → waypoint queue (ordered, numbered) | M | both? | Keep |
| Queued-path preview polylines | M | mission | Keep |
| BT MoveTo coroutine + generation-token cancel | M | both | Keep |
| Pause-on-danger (enemies within radius) + danger radius cfg | M | both | Keep |
| Arrival detection + auto-advance queue + auto-clear | M | mission | Keep |
| Stop button (cancel move + clear queue) | M | mission | Keep |
| Snap path drawn as 3D BT move path overlay | M | mission | Keep |

## Positioning / window

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Snap overlay to live game frame | C+M | both | Keep |
| Detached/floating mode (choose pos + size) | C | compass | Keep — compass-only |
| Always-point-north (detached) | C | compass | Keep |
| "Snap to screen center" button | C | compass | Keep |
| Floating Move toggle button | M | mission | Keep |
| Floating Map-ID strip | M | mission | Keep |
| Floating coords strip (+Copy) | M | mission | Keep |
| Floating mega-zoom slider (zoom ≥ 3.5) | M | mission | Keep |

## Config / persistence

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| Per-marker: visible/size/shape/color(+accent)/fill | C+M | both | Keep — superset |
| Per-marker fill range + fill color | C | both | Keep |
| Range-ring persistence | C | both | Keep |
| Custom-marker persistence (by model-id) | C | both | Keep |
| Terrain settings persistence | M | both | Keep |
| Snap settings persistence | M | both | Keep |
| Auto-save on change (no Save button) | M | both | Keep — house style |
| Grouped config editor (Party/Hostile/World/Spirits) | M | both | Keep |
| Full config editor incl. rings + custom + pathing | C | both | Keep — merge editors |
| Settings scope | C=global, M=account | — | **Decide** — likely account; plan migration |

## Boilerplate / plumbing

| Feature | Source | Frame | Notes / Keep? |
|---|---|---|---|
| `tooltip()` with title/features/credits | C+M | — | Keep one; **fix** Compass's mislabeled title |
| `configure()` window | C+M | — | Merge into one |
| `main()` / `draw()` entry + error logging | C+M | — | Keep one |
| Widget-frame open/visible gating | C+M | — | Keep — per frame |

## Features NOT to lose (headline uniques)

- **Compass-only:** rotation, custom-markers-by-model-id + Get-from-Target, ritualist spirit
  sub-ranges, profession boss colors, range-ring editor, detached mode + north-lock, culling.
- **Mission-Map-only:** NavMesh snap-move + waypoint queue + previews + danger-pause, terrain
  mega-zoom, coords copy strip, map-id strip, terrain color config, single-struct agent read,
  auto-save settings, per-map caches.
