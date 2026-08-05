# ImGui Documentation Map

This folder contains Py4GW ImGui implementation guidance, historical facade proposals, and behavior classification.

## Current implementation authority

- The active wrapper is the implementation identified by the current project source and root instructions; verify imports and ownership in `Py4GWCoreLib/ImGui.py` and its owning implementation before changing code.
- The `ImGuiRuntime` facade migration described by the documents below is historical/dead unless current source and an explicit user decision revive it.
- Do not treat a design document's “source of truth” wording as proof that its proposed runtime still exists.

## Document roles

| Document | Role | Status/use |
|---|---|---|
| `HTML_Mockup_to_ImGui_Guide.md` | Porting workflow | Practical guide; validate binding names and runtime behavior against current stubs/source |
| `ImGui_Legacy_Functionality_Categorization.md` | Legacy behavior classification | Historical analysis for preserving/replacing functionality; not an implementation plan |
| `ImGui_Facade_Migration_Plan.md` | New-facade design specification | Historical proposal for the abandoned `ImGuiRuntime` facade; do not implement without explicit revival |
| `ImGui_Implementation_Correction_Instructions.md` | Corrective handoff | Historical instructions coupled to the abandoned facade; not current runtime authority |
| `ImGui_Layer2_Ergonomics_Proposal.md` | Layer-2 ergonomics proposal | Explicitly parked exploratory work; no code implied |
| `FloatingIcon_Class.md` | Floating icon behavior guide | Active helper reference; verify against `ImGui_src/ImGuisrc.py`; historical `ImGui_Legacy`/`IniManager` wording is flagged in the document |

## Contradiction rule

- Current source, active project instructions, and injected-client evidence outrank these historical plans.
- Preserve useful invariants from the abandoned proposals only when they match the active owner and binding model.
