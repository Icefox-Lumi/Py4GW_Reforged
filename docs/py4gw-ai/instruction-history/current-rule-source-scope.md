# Current Py4GW Rule-Source Scope Map

This document records where the existing Py4GW rules and knowledge live before a replacement instruction file is designed.

No source file listed here is modified by this document.

## Source Project

Primary project inspected:

`C:\Users\Apo\Py4GW_Reforged`

Related projects referenced by its rules:

- `C:\Users\Apo\Py4GW_Reforged_Native`
- `C:\Users\Apo\Py4GW`
- `C:\Users\Apo\Py4GW_python_files`
- `C:\Users\Apo\D3CA`

## Root Instruction Files

### `AGENTS.md`

Scope: project-wide agent guidance for the repository.

Observed content classes:

- Persistence and storage rules
- Legacy GWCA to Reforged Native migration status
- Documentation hierarchy
- Reverse-engineering methodology and tool locations
- Function and UI-message mappings
- Entry points
- Focused verification commands
- Repository-specific gotchas
- Python, C++, native, bridge, widget, and runtime facts
- Source-of-truth distinctions between current and legacy projects

### `CLAUDE.md`

Scope: project-wide Claude-oriented guidance for the repository.

Observed content classes:

- Project identity and runtime model
- Legacy source locations and parity rules
- Reforged Native migration rules
- ImGui facade status and canonical wrapper
- Documentation reading order
- Environment and tooling constraints
- Layered architecture model
- Entry points
- Targeted verification
- Repository conventions and gotchas

The two root files overlap substantially but are not identical. They must be compared as separate sources before consolidation.

## Tool Configuration and Permission Files

### `.codex/config.toml`

Scope: Codex configuration for this project.

Observed content:

- Ghidra MCP server command
- Python interpreter path
- Ghidra MCP transport mode
- Ghidra MCP and debugger URLs
- Python encoding environment setting

Classification: runtime/tool configuration, not project knowledge by itself.

### `.claude/settings.local.json`

Scope: local Claude permissions and tool authorization.

Observed content classes:

- Ghidra MCP tool permissions
- Python/Bash/PowerShell permissions
- Read permissions for Py4GW and native repositories
- CMake/build permissions
- Search, inspection, and reverse-engineering commands
- File-copy, migration, and cleanup commands
- Pyright/type-check commands
- Web and documentation tools
- Runtime/build/log inspection commands

Classification: local execution policy and capability configuration, not durable Py4GW domain guidance.

### `.opencode/opencode.json`

Scope: OpenCode project configuration.

Observed content:

- OpenCode schema reference
- Default model selection

Classification: runtime/model configuration.

## OpenCode Agents

Directory: `.opencode/agents/`

Scope: role-specific agent behavior selected by OpenCode workflows.

Files and observed roles:

- `workflow-orchestrator.md` — intake-first coordination, approval gate, delegation, task artifacts
- `implementer.md` — approved-plan execution, no architectural improvisation
- `verifier.md` — plan adherence and targeted verification
- `docs-writer.md` — documentation after technical stabilization and verification
- `research-scout.md` — fast parallel research and ecosystem investigation
- `consensus-synthesizer.md` — merge reports while preserving disagreement and confidence
- `planner.md` — intake-to-plan conversion, assumptions, file targets, validation, rollback
- `intake-analyst.md` — repo-aware intake refinement and user approval
- `intake-opponent.md` — feasibility and hidden-assumption criticism
- `opponent.md` — plan/execution critique, edge cases, test gaps, alternatives

Classification: workflow roles and behavioral specializations. These are not all global project rules.

## OpenCode Commands

Directory: `.opencode/commands/`

Scope: manually invoked workflow entrypoints.

Files and observed roles:

- `intake.md` — general intake approval loop
- `intake-bug.md` — bug/regression intake
- `intake-feature.md` — feature intake
- `intake-refactor.md` — refactor intake
- `intake-research.md` — research/decision-support intake
- `intake-reverse-engineering.md` — reverse-engineering intake
- `intake-widget.md` — widget/widget-manager/catalog intake
- `intake-bridge.md` — bridge/daemon/CLI/MCP intake
- `plan.md` — plan creation/refinement
- `research.md` — research swarm
- `implement.md` — approved-plan implementation
- `verify.md` — plan and acceptance verification
- `verify-bridge.md` — bridge-specific verification
- `document.md` — post-change documentation
- `consensus.md` — decision-brief synthesis
- `task-status.md` — task state and workflow status

Classification: workflow commands. Their underlying procedures may contain rules worth extracting, but command syntax itself is tool-specific.

## OpenCode Skills

Directory: `.opencode/skills/`

Scope: reusable knowledge and procedures loaded by OpenCode.

Files and observed roles:

- `py4gw-core/SKILL.md` — Py4GW layout, imports, docs, widgets, bridge, startup constraints
- `py4gw-reforged-python-core/SKILL.md` — injected Python runtime, architecture, entrypoints, bridge, sensitive areas
- `reforged-python-bridge/SKILL.md` — injected bridge widget, daemon, CLI, MCP, safe runtime surface
- `re-methodology/SKILL.md` — WASM-first reverse engineering and Ghidra program selection
- `reforged-python-re-methodology/SKILL.md` — Py4GW-specific reverse-engineering workflow and references
- `verification-playbook/SKILL.md` — targeted validation and repository-aware commands
- `reforged-python-verification/SKILL.md` — Py4GW targeted scripts, bridge checks, and smoke tests
- `doc-authoring/SKILL.md` — documentation target selection and canonical-source preservation
- `reforged-python-doc-authoring/SKILL.md` — Py4GW documentation hierarchy
- `workflow-patterns/SKILL.md` — intake gate, workflow archetypes, phase handoffs
- `deepseek-routing/SKILL.md` — model routing by speed/depth

Classification: highest-density source of reusable Py4GW knowledge and procedures. Each item needs separate extraction into facts, rules, workflows, or references.

## OpenCode Templates

Directory: `.opencode/templates/`

Scope: structure of task artifacts produced by workflows.

Templates:

- `intake.md` — working draft, approved intake, user approval log
- `state.md` — request, intake, objective, outcome, scope, constraints, rules, assumptions, facts, unknowns, questions, acceptance, risk, workflow, phase, routing, approval
- `research.md` — question, search angles, findings, contradictions, sources, confidence, gaps
- `plan.md` — version, scope, impacted systems, assumptions, rejected alternatives, steps, validation, rollback, critique, approval
- `verification.md` — checks, results, failures, required fixes, residual risk
- `docs.md` — affected documentation, changes, follow-up notes

Classification: workflow-state and reporting schemas. These reveal required reasoning fields but are not themselves technical Py4GW rules.

## OpenCode Task Records

Directories:

- `.opencode/tasks/active/`
- `.opencode/tasks/archive/`

Scope: individual task state, research, plans, diagnostics, and verification records.

Observed active task areas include:

- Dictionary-attribute bug
- Context-pointer migration
- ImGui facade migration
- ImGui migration audit
- Bindings/pointers/shared-memory migration

Classification: task-scoped and historical knowledge. These records may contain valuable Py4GW facts, decisions, failures, and verification evidence, but they should not automatically become global rules.

## Extraction Targets

Each source item can be classified during consolidation as:

- Durable project rule
- Verified project fact
- Source-of-truth pointer
- Architecture decision
- Workflow procedure
- Role behavior
- Tool/runtime configuration
- Permission policy
- Task-specific state
- Historical evidence
- Template/schema
- Open question or unresolved assumption

This classification is a source map only. It does not select which items belong in the replacement file.
