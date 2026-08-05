# LaunchSurface Documentation Map

This folder contains the LaunchSurface framework design, authoring guides, user instructions, and runtime/UI audits.

## Authority and status

| Document | Role | Use it for |
|---|---|---|
| `LaunchSurface_Framework_Design.md` | Architecture and model design | Ownership, host/provider boundaries, model APIs, intended feature coverage, and implementation structure |
| `LaunchSurface_UI_Feature_Audit.md` | Live-host feature audit and release gate | What the current runtime actually exposes; this outranks design promises when they conflict |
| `LaunchSurface_Quality_Audit.md` | Quality/refinement record | Interaction defects, remediation rationale, and audit follow-up; follow its link to the feature audit |
| `LaunchSurface_User_Manual.md` | Operator guidance | Current startup, editing, persistence, and known runtime limitations |
| `LaunchSurface_Component_Guide.md` | Embedded-component authoring | Component lifecycle, state, rendering, and registration contracts |
| `LaunchSurface_Provider_Guide.md` | Provider authoring | How to register project actions/components without taking ownership of layout or discovery |

## Contradiction rule

- Treat the design as the intended architecture, not proof that a feature is live.
- Treat the UI feature audit and injected-client evidence as authoritative for current behavior and release readiness.
- When the user manual and implementation disagree, inspect `LaunchSurface.py` and verify in the injected client before updating either document.

