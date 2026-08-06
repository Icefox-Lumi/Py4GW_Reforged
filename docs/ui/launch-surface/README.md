# LaunchSurface Documentation Map

This folder contains the LaunchSurface framework design, authoring guides, user instructions, and runtime/UI audits.

## Authority and status

| Document | Role | Use it for |
|---|---|---|
| `launch-surface-framework-design.md` | Architecture and model design | Ownership, host/provider boundaries, model APIs, intended feature coverage, and implementation structure |
| `launch-surface-ui-feature-audit.md` | Live-host feature audit and release gate | What the current runtime actually exposes; this outranks design promises when they conflict |
| `launch-surface-quality-audit.md` | Quality/refinement record | Interaction defects, remediation rationale, and audit follow-up; follow its link to the feature audit |
| `launch-surface-user-manual.md` | Operator guidance | Current startup, editing, persistence, and known runtime limitations |
| `launch-surface-component-guide.md` | Embedded-component authoring | Component lifecycle, state, rendering, and registration contracts |
| `launch-surface-provider-guide.md` | Provider authoring | How to register project actions/components without taking ownership of layout or discovery |

## Contradiction rule

- Treat the design as the intended architecture, not proof that a feature is live.
- Treat the UI feature audit and injected-client evidence as authoritative for current behavior and release readiness.
- When the user manual and implementation disagree, inspect `LaunchSurface.py` and verify in the injected client before updating either document.

