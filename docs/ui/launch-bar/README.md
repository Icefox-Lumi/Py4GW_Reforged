# LaunchBar Documentation Map

This folder contains the LaunchBar design and implementation planning record.
LaunchBar is the current widget-manager UI; `LaunchSurface` is the preceding
UI framework and remains useful for historical comparison.

## Authority and status

- `launch-bar-im-gui-implementation-plan.md` records the locked interaction model,
  intended layers, persistence shape, and original implementation scope.
- The plan's original "not yet implemented" status is stale. The current
  implementation is under `Py4GWCoreLib/py4gwcorelib_src/launch_bar/` and is
  hosted from `Py4GW_widget_manager.py`.
- Current source, focused checks, and injected-client behavior outrank the
  plan when describing what is live or complete.
- The plan's out-of-scope statements describe its original pass; do not infer
  that the same behavior is absent from the current package without checking
  the source.

## Related records

- `../launch_surface/README.md` — authority map for the predecessor framework,
  its guides, audits, and user manual.
- `../imgui/html-mockup-to-im-gui-guide.md` — ImGui porting workflow and the
  worked-plan companion link.
- `Py4GWCoreLib/py4gwcorelib_src/launch_bar/` — current model, host, manager,
  persistence, runtime, and application entry point.
- `Py4GW_widget_manager.py` — in-client host that bootstraps widgets and draws
  the launchpad each frame.

## Review order

1. Read the plan for intended interaction and layer boundaries.
2. Inspect the current `launch_bar` package for actual behavior and ownership.
3. Compare LaunchSurface records only when migration or compatibility is in scope.
4. Verify UI behavior in the injected client when offline source inspection is
   insufficient.
