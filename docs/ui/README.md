# UI and Rendering Documentation

Use this directory for PyImGui, native-overlay, frame-tree, launch-surface,
and widget presentation records.

- `imgui/` — PyImGui wrapper and ImGui migration/ergonomics records.
- `frame_tree/` — frame-tree design and implementation status.
- `launch_bar/` and `launch_surface/` — launcher surfaces and providers.
- `overlay/` — 3D-overlay performance evidence.
- `widget_manager/` — widget discovery, metadata, and catalog ownership.

Do not transfer web UI assumptions into the injected ImGui runtime.
