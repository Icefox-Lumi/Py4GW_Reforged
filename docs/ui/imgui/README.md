# ImGui Documentation Map

This folder contains Py4GW ImGui implementation guidance. Historical facade
proposals and legacy behavior classification are preserved under `archive/`.

## Current implementation authority

- The active wrapper is the implementation identified by the current project
  source and root instructions; verify imports and ownership in
  `Py4GWCoreLib/ImGui.py` and its owning implementation before changing code.
- The `ImGuiRuntime` facade migration described by the archived documents is
  historical/dead unless current source and an explicit user decision revive
  it.
- Do not treat a design document's "source of truth" wording as proof that its
  proposed runtime still exists.

## Document roles

| Document | Role | Status/use |
|---|---|---|
| `html-mockup-to-im-gui-guide.md` | Porting workflow | Practical guide; validate binding names and runtime behavior against current stubs/source |
| `floating-icon-class.md` | Floating icon behavior guide | Active helper reference; verify against `ImGui_src/ImGuisrc.py`; historical `ImGui_Legacy`/`IniManager` wording is flagged in the document |
| `../../archive/ui/imgui/` | Abandoned-facade records | Historical proposals, classification, and corrective handoffs for the abandoned `ImGuiRuntime` facade; see `../../archive/README.md` |

## Contradiction rule

- Current source, active project instructions, and injected-client evidence
  outrank these historical plans.
- Preserve useful invariants from the abandoned proposals only when they match
  the active owner and binding model.
