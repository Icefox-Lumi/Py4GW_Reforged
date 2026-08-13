# FloatingIcon Class

Status: current source reference; live injected-client acceptance remains feature-specific
Scope: `ImGui.FloatingIcon` runtime toggle and window-geometry ownership
Authority: `Py4GWCoreLib/ImGui_src/ImGuisrc.py`

`ImGui.FloatingIcon` is a small draggable icon that toggles a callback. The
historical `ImGui_Legacy` name sometimes remains in callers and older records;
do not use that name as evidence for a persistence API.

## Ownership

The helper owns only current-frame icon behavior:

- icon drawing, drag detection, and click-versus-drag behavior;
- the current `visible` toggle state and optional callback;
- the public `position` observed after the icon window begins.

The consumer owns feature persistence policy. There are two supported modes:

| Mode | `persist_window_state` | Geometry owner |
|---|---:|---|
| Default compatibility mode | `True` | Native ImGui, keyed by the unique icon window name. |
| Reforged feature-owned mode | `False` | The consuming feature's jailed `Settings` document. |

The default preserves existing callers. A feature that needs account-scoped or
otherwise explicit geometry must opt out. In that mode the helper adds
`NoSavedSettings`; it does not create a second persistence document.

## Constructor

Important parameters:

- `icon_path`, `button_size`, `idle_icon_scale`, `hover_icon_scale`: render inputs.
- `start_pos`: first in-memory position before any caller restoration.
- `window_id`, `window_name`: unique ImGui identity; callers must not collide.
- `visible`, `on_toggle`, `draw_callback`: session toggle and controlled body.
- `toggle_ini_key`, `toggle_section`, `toggle_var_name`, `toggle_default`:
  optional account-`Settings` route for the functional toggle only.
- `persist_window_state`: `True` by default. Pass `False` for caller-owned
  geometry persistence.

## Functional-toggle persistence

When `toggle_ini_key` and `toggle_var_name` are set, `load_visibility()` and
`save_visibility()` use `Settings(toggle_ini_key, "account")`. Native Settings
owns binding and autosave. A caller without those fields keeps visibility as
session state; it must not create a separate visibility owner merely because
the icon happens to be visible.

## Feature-owned geometry pattern

For `persist_window_state=False`:

1. Construct the icon with a stable ID and `persist_window_state=False`.
2. Wait until the feature's account `Settings` document reports ready.
3. Read its saved `x`/`y` once and call `reposition_to((x, y))`.
4. Call `floating_button.draw()` each frame.
5. After draw, save the changed public `floating_button.position` through that
   same document. Native Settings debounces the write.

Do not read `imgui.ini`, create a raw INI path, or use `ini_key` as a
configuration route. `draw(ini_key="")` retains its argument solely for
compatibility; current `ImGui.Begin` ignores it.

## Minimal example

```python
floating_button = ImGui.FloatingIcon(
    icon_path=icon_path,
    window_id="##my_feature_icon",
    window_name="My Feature Toggle",
    visible=True,
    draw_callback=draw_feature_window,
    persist_window_state=False,
)

# Once Settings("Widgets/MyFeature.ini", "account") is ready:
floating_button.reposition_to((saved_x, saved_y))

# Per frame:
floating_button.draw()
saved_x, saved_y = floating_button.position
```

The caller must still use its normal close-hand-off if the controlled window
can close independently. `sync_begin_with_close(open_)` updates the icon's
toggle state; it does not manage the consuming window's persistence.
