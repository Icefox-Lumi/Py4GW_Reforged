# Demo Replacement — Context & Analysis

Context gathering for the Py4GW demo/test widgets. These scripts exist to
**exercise and validate the whole CPP Native backend** — the `Py*` bindings,
the Python wrappers, and the datasource/context paths — from inside the live
game client.

**Related backend project:** `C:\Users\Apo\Py4GW_Reforged_Native` (the C++
DLL that publishes the `Py*` modules).

> Status: **replacement built.** The build plan completed with 44 sections
> registered (see `archive/build-plan.md`); the current build's surface and
> the pending re-engineer proposal live in `research/`. The pre-build
> analysis and inventory records are historical evidence preserved under
> `archive/`.

## Live references

- [`contexts.md`](contexts.md) — native context structs ↔ `native_src/context`
  ctypes readers, field inventories (18 contexts).
- [`python-wrapper-api.md`](python-wrapper-api.md) — per-domain wrapper
  getter/action surface (~620 getters / 240 actions, 25 wrappers).
- [`research/`](research/README.md) — the current evidence base and the
  pending re-engineer spec: original demo patterns (R1), binding-method
  inventory (R2), wrapper casting (R3), current-shortcut audit (R4), and the
  approval-gated `spec-reengineer.md`.

## Archived analysis (historical evidence)

The pre-build analysis and plan are preserved under
[`../../archive/validation/demo/`](../../archive/validation/demo/):
v1/v2 inventories, the coverage matrix, backend and C++-binding inventories,
reusable-script harvest list, the completed build plan, gaps analysis, and
transitional debug notes. Read them for the history of how the replacement
was scoped, not as a description of the current demo surface.

## One-paragraph summary

DEMO v1 was a complete-but-legacy, monolithic "show every method and all
data" widget built on `GLOBAL_CACHE` + `ImGui_Legacy`, covering all 13
gameplay domains but only shallowly against the Reforged backend. The
replacement adopted v2's modular shell (`Sources/` package, sidebar window,
native `PyImGui`, dataclass state) and completed a build covering all 23
gameplay `Py*` modules and ~15 infra modules across 44 registered sections;
the re-engineer spec in `research/` is the next, approval-gated step.
