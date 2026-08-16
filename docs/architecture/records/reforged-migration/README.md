# Reforged Migration Records

This folder contains migration-session records and parity/severance analysis.

Current status: the FrenkeyLib migration worktree was rejected on 2026-08-12
and its Python changes were reverted to base `01cfb912`; the rejected records
remain historical. Read `frenkeylib-migration-failure-and-rollback-record.md`
first. It is the current authority for preservation and recovery, and no
document below authorizes further Factory-led conversion or destructive
rollback.

- `frenkeylib-itemmanager-port-plan.md` is the proposed minimal-shim plan for
  porting the `data_collection` branch feature set. It follows the rejected
  records' non-negotiable controls and supersedes none of them. It also records
  the 2026-08-13 LootEx widget port: the LootEx widget plus its
  `Sources/frenkeyLib/LootEx`, `SulfurousRunner`, and shared `Core` packages,
  shimmed from the legacy branch onto the Reforged surfaces. Live-client load
  remains the outstanding acceptance gate.

- `frenkeylib-boundary-compliance-plan.md` is the active migration step:
  remove all remaining shims and move every active FrenkeyLib flow onto its
  Reforged owner directly — `Settings` and `JsonFactory` for persistence, and
  native ImGui persistence for window geometry and state. Phase 1 (configs,
  profiles, ItemData, DataCollector) is executed in the worktree; seeds, the
  one-time data import, and live-client verification remain.

- The native filter-domain contract (evaluation → filter → filter set, no
  profile layer) lives in `docs/loot/redesign/filter-structure.md` — it
  belongs to the `Item.Mods` side, not to this folder. FrenkeyLib's own mod
  handling is a separate legacy domain that migrates onto `Item.Mods`
  eventually.

- `session-01-intake.md` and `session-01-complete.md` record one migration
  session and its conclusions.
- `frenkeylib-severance-audit.md` records dependency and compatibility findings.
- `frenkeylib-migration-failure-and-rollback-record.md` is the current failure,
  preservation, and rollback-design authority.
- `frenkeylib-rollback-file-manifest.md` is the file-level preservation and
  classification index for the Python and Native worktrees.
- `frenkeylib-decision-autopsy.md` is the detailed decision analysis: adopted
  premise, contradictory evidence, code consequence, verification failure,
  and prevention rule for the rejected path.
- `frenkeylib-complete-cutover-plan.md` is a superseded proposed execution
  plan. It records the rejected Factory-led direction.
- `frenkeylib-layered-migration-plan.md` is the detailed historical execution
  journal for that rejected direction.
- `frenkeylib-stage-0-cutover-ledger.md` records the resulting source claims
  and exclusions; it is historical evidence, not current migration authority.

Use this folder with the owning current Python and native sources. Session logs
are historical evidence and cannot establish current runtime behavior alone.
