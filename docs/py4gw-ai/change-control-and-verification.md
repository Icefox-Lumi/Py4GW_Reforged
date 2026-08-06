# Change Control and Verification

Status: current delegated guidance
Scope: tools, file changes, Git safety, testing, builds, and migration traceability

## Tool Usage


- Use available specialized tools only for task inspection, modification, verification, or completion; do not invoke them for unrelated activity.
- Prefer file-reading/search/exploration tools for inspection, file-editing tools for changes, and write/create tools only when a necessary artifact has no suitable existing file.
- Use the shell for terminal operations, Git, builds, tests, and scripts; handle redirected URLs by following the final relevant destination.
- Do not invoke destructive Git or filesystem commands without explicit authorization for the specific action and target. This is a behavioral rule; use host approvals, sandboxing, wrappers, or deny-lists for technical enforcement.
- Run safe independent calls in parallel; keep dependent calls sequential so each uses the preceding evidence.
- Do not use tools, comments, shell output, or raw results as communication channels; explain results to the user separately.
- Follow host approval/escalation behavior and treat declared tool capabilities and limitations as execution constraints.

## File Editing


- Use patch-based or specialized edit tools; prefer a focused patch for single-file changes.
- Use scripting only for mechanical or bulk edits where it reduces risk, then inspect the result.
- Do not manually edit generated files; change their source or generation process.
- Preserve existing encoding and default to ASCII; introduce Unicode only for an explicit project, user-facing, or technical need.
- Add comments only for non-obvious behavior, ownership, constraints, or decisions.
- Avoid new files when an appropriate existing file can be extended; never create a parallel source of truth.

## Repository and Workspace Hygiene


- Confirm the active target repository and workspace boundary before editing.
- Preserve dirty worktrees, user changes, and unrelated modifications; inspect status, overlapping edits, and relevant diffs before touching affected files.
- Do not revert, restore, overwrite, reset, or destructively checkout user work; ignore unrelated changes rather than folding them into the task.
- Keep writes within the requested repository, sibling project, or external path only when explicitly in scope.

## Git and Change Management


- Check Git status before editing and when reporting the resulting state; inspect history or `git blame` when ownership, rationale, migration, or provenance matters.
- HARD RULE: never run destructive Git commands without explicit authorization for the exact action and target. This includes reset, destructive checkout/restore, clean, force-push, branch deletion, history rewriting, and equivalents; implementation, cleanup, review, or verification requests do not authorize them.
- If destructive scope is not exact and unambiguous, inspect status/diffs and ask one targeted clarification. Never commit unless the user explicitly requests it.
- Preserve unrelated changes and exclude them from the task change set.
- Review compatibility for public Python/native/bridge/runtime APIs, CLI behavior, configuration/persistence, and session-resume state when affected.
- Keep changes proportionate and split oversized work by conceptual behavior, migration, formatting, or infrastructure concern.

## Repository Safety and Change Control


- Require explicit authorization and a clear target/scope before any destructive Git or filesystem action.
- Before acting, inspect status and relevant diffs, preserve unrelated/uncommitted changes, and prefer recoverable alternatives.
- If scope remains ambiguous, finish safe investigation and ask one targeted clarification; do not ask permission for routine reversible work.

## Traceable Changes and Migration Analysis


- Prefer additive, traceable changes over opaque rewrites; preserve source structure, method names, call paths, initialization order, and public contracts unless change is required.
- Keep migrations small, reversible, buildable, and reviewable; separate movement, formatting, architecture, and behavior changes and classify the change before implementation.
- Reuse the owning class or approved library; modify or extend it instead of duplicating or creating a parallel replacement.
- Do not use monkey patches, external method replacement, method shadowing, hidden wrapper entry points, or incidental override points as architecture.
- Require explicit owner-controlled extension points, one authoritative owner, and one explicit integration path.
- Keep related changes together when it improves Git traceability, preserve recognizable history, and track ownership, lifecycle, dependencies, and contract changes in the plan or review record.

## Testing and Verification


- Inspect existing repository verification before adding tests. Run Pyright/Pylance for changed Python with the strict project configuration, report target/command/result, and treat new errors as failures; never weaken or hide diagnostics.
- Tests must emit readable, attributable diagnostics containing relevant inputs, state, expected and observed outcomes, and failure context through the approved console logger or `print` mechanism.
- For injected-client failures, obtain crash logs from the injected-client folder (with authorization if needed), correlate them with the injection log, timestamps, build/runtime context, and reproduction, and preserve observed evidence separately from inference.
- Run focused checks first, then expand to integration, native, injection, or runtime verification when the change crosses those boundaries; distinguish offline proof from live-client proof.
- Follow existing test practice; do not introduce a new test framework without explicit scope. Keep dedicated tests near the owning implementation and use integration tests for cross-repository, tool, bridge, or runtime behavior when a suitable path exists.
- Prefer complete-object comparisons, avoid tests for static or removed logic, and use existing performance benchmarks/smoke tests for frame- or runtime-sensitive changes.
- Keep test environments stable: avoid mutating process environment, resolve binaries/resources deterministically, and mock unstable external responses at boundaries.

## Build, Formatting, and Dependencies

- Run repository-approved formatters, Python PEP 8 formatter/linter checks, scoped lint/fix commands, and affected-subsystem tests; do not claim checks passed when they were not run.
- Expand to full suites for shared or cross-cutting Python, native, bridge, injection, or runtime changes; avoid broad matrices that add no confidence.
- Update lockfiles, generated schemas, or build metadata when the repository's dependency/configuration/build process requires it.
- Install missing repository tools only when required and in scope.
- Treat long-running Python, native, injection, and integration builds accurately; do not report incomplete runs as success or failure.
