# Py4GW Runtime Conventions

Status: current delegated guidance
Scope: injected script lifecycle and ImGui runtime rules

## Py4GW Script and Runtime Conventions


- Follow the established Py4GW script lifecycle; `update()` is the non-UI per-frame entry point, while `draw()` and `main()` are UI per-frame callbacks when used. None is a one-time startup function by default.
- Use the standard PyImGui window skeleton for scripts within scope; explicitly recognize exemptions for libraries, tests, headless utilities, native-only components, and other non-UI scripts.
- Log debug diagnostics to the approved console mechanism with defined levels and enough context to identify the script, lifecycle stage, function, and execution case.

## Py4GW ImGui Scope and Conventions


- Treat Py4GW ImGui as immediate-mode UI re-described every frame; use `import PyImGui` directly or the established `Py4GWCoreLib` re-export according to local convention.
- Apply single-runtime/facade migration rules only when that migration is explicitly in scope; otherwise preserve the current binding and facade ownership.
- Keep ImGui state, stack tracking, grouped surfaces, diagnostics, and persistent runtime state owned by the established runtime; do not create ad hoc or competing persistence systems.
- Use context-managed structural scopes with explicit `.entered` results and cleanup semantics; treat underflow as an immediate error and frame-end imbalance as an observable diagnostic.
- Give window persistence one authoritative owner; namespace IDs and define ownership for input capture, focus, popups, child windows, and embedded components.
- Reuse existing Settings and runtime diagnostic paths; keep persistence, rendering, and runtime failures observable.
- Validate native input, Settings binding, and live injected-client behavior when offline checks cannot prove them. Do not apply web, HTML/CSS, or responsive-design assumptions.
