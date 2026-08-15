# INI and Settings Documentation Map

This folder records the completed `IniManager`/`IniHandler`/`configparser` to
`Settings` migration. All migration plans, handovers, and the removed-API
behavior guide are historical and preserved under
`../../archive/persistence/ini-manager/`; see `../../archive/README.md`.

## Current implementation evidence

- `Py4GWCoreLib/py4gwcorelib_src/Settings.py` is present and is the active
  Python settings implementation.
- `Py4GWCoreLib/IniManager.py` and
  `Py4GWCoreLib/py4gwcorelib_src/IniHandler.py` are absent from the current
  tree.
- `Widgets/Automation/Helpers/Pycons.py`, `Widgets/System/Messaging.py`,
  `Py4GW_Launcher.py`, and any legacy/deprecated trees must be checked
  separately because their persistence boundaries differ.
- Current source and runtime evidence outrank plans, handovers, and historical
  claims in the archive.

## Review sequence

1. Read the archived records for intent and known failure modes; note that
   several report completion while leaving native rebuild or live-client
   verification open.
2. Inspect `Settings.py`, the native `PySettings` implementation, and the
   affected caller.
3. Check active-tree searches for remaining `configparser`, `IniHandler`, and
   `IniManager` usage.
4. Verify native build/runtime state before treating any archived status as
   current.
