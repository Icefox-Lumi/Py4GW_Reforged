# INI and Settings Documentation Map

This folder groups the historical and operational documents about `IniManager`, `IniHandler`, `configparser`, and the native-backed `Settings` surface.

## Current implementation evidence

- `Py4GWCoreLib/py4gwcorelib_src/Settings.py` is present and is the active Python settings implementation.
- `Py4GWCoreLib/IniManager.py` and `Py4GWCoreLib/py4gwcorelib_src/IniHandler.py` are absent from the current tree.
- `Widgets/Automation/Helpers/Pycons.py`, `Widgets/System/Messaging.py`, `Py4GW_Launcher.py`, and any legacy/deprecated trees must be checked separately because their persistence boundaries differ.
- Current source and runtime evidence outrank plans, handovers, and historical claims in this folder.

## Document authority and status

| Document | Role | Status interpretation | Authority |
|---|---|---|---|
| `ini-manager-behavior-and-usage-guide.md` | Behavior guide for the former `IniManager`/`IniHandler` API | Historical; describes removed APIs such as `load_once()` and `save_vars()` | Do not use as current implementation truth without rechecking source |
| `ini-manager-migration-handover.md` | Requirement-only handover | Historical requirement; intentionally contains no validated approach | Context only |
| `ini-manager-migration-plan.md` | Locked migration execution plan | Historical execution record; superseded by later removal records | Use for decisions and mappings that remain relevant, not as current procedure |
| `ini-manager-gut-to-settings-plan.md` | Detailed migration design and failure analysis | Historical record; contains both “plan only” language and later completion claims | Use as migration evidence; resolve claims against source/runtime |
| `ini-handler-removal-plan.md` | Removal execution record | Marked done, with explicit cross-account and local-copy follow-ups | Historical record plus follow-up checklist |
| `ini-manager-removal-plan.md` | `IniManager` shell removal record | Marked executed; still calls out in-client verification and out-of-scope legacy consumers | Historical record plus verification checklist |
| `configparser-to-settings-migration-plan.md` | Final configparser classification/migration record | Marked complete but still requires native rebuild/live verification in its status block | Historical record; update references and verify runtime state |

## Known contradictions requiring evidence

- Several documents report migration completion while also listing native rebuilds, live-client verification, or remaining consumers as open. Do not collapse those statements into one status without checking the current code, native build, and runtime logs.
- `ini-manager-gut-to-settings-plan.md` contains an internal transition from “plan only” to completion claims; preserve that history and treat the implementation and runtime evidence as authoritative.
- The behavior guide describes APIs that were removed; it is useful for understanding historical callers and persistence semantics, not for writing new code.
- `configparser-to-settings-migration-plan.md` distinguishes durable settings from transient cross-client coordination; preserve that distinction when reviewing `Messaging.py`.

## Review sequence

1. Read the relevant historical record for intent and known failure modes.
2. Inspect `Settings.py`, the native `PySettings` implementation, and the affected caller.
3. Check active-tree searches for remaining `configparser`, `IniHandler`, and `IniManager` usage.
4. Verify native build/runtime state before changing a document's status from historical or unresolved to current.

