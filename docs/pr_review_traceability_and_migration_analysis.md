# PR Review Guide: Traceable Refactors and Migration Analysis

## Purpose

Use this guide when reviewing a pull request that reorganizes, migrates, extracts, or rewrites an existing feature.

The objective is not only to determine whether the new code works. The review must also determine whether the change remains understandable, traceable, reversible, and safe for future human and AI maintainers.

This guide is especially important for migrations from legacy code, architecture changes, framework replacements, and large refactors presented as “no-op” changes.

## Project vision

The preferred change is additive and traceable:

- Preserve the existing source structure whenever practical.
- Keep related changes in the same source file when that allows Git to show the change clearly.
- Make one conceptual change per commit or pull request.
- Preserve method names, call paths, initialization order, and public contracts unless the change explicitly requires otherwise.
- Make the original implementation recognizable while it is being reorganized.
- Keep each intermediate state buildable and testable.
- Prefer a sequence of small, reversible migrations over a parallel replacement implementation.

Runtime equivalence is necessary, but it is not sufficient. A refactor that behaves the same today can still be unacceptable if it destroys source history, hides dependencies, prevents useful review, or makes future regressions difficult to diagnose.

## Core distinction: logic rewrite versus structural rewrite

Do not accept the author’s description without inspecting the diff.

A pull request may be:

| Type | Meaning | Review expectation |
| --- | --- | --- |
| Additive change | Adds a new path while preserving the existing path | Verify compatibility and controlled adoption |
| Mechanical relocation | Moves code without changing behavior | Require source-level traceability and proof of equivalence |
| Structural refactor | Changes files, classes, inheritance, or ownership | Review contracts, initialization, MRO, and dependency boundaries |
| Semantic change | Changes runtime behavior or policy | Require explicit behavior specification and tests |
| Rewrite | Recreates the feature using a different structure or implementation | Usually request decomposition before approval |

“The method bodies are AST-identical” proves only one narrow property. It does not prove that class construction, method resolution, imports, initialization order, lifecycle, exception behavior, or integration behavior are unchanged.

## Review workflow

### 1. Capture the requested vision before reviewing the implementation

Write down the constraints that the change must satisfy. At minimum, identify:

- Is this a migration, bug fix, extraction, or behavior change?
- Is the existing implementation expected to remain recognizable?
- Is a new file or class actually required?
- Must the old API remain compatible?
- Are scripts being retired, or must they continue to work during transition?
- Are settings, persistence, callbacks, queues, or native bindings subject to repository-specific rules?
- Must the change be pyright/Pylance clean?
- Does the user require the current behavior to remain unchanged?

If the vision is unclear, ask before evaluating architecture. Do not silently replace “migrate” with “rewrite.”

### 2. Establish the baseline

Record the base and head commits, changed files, and working-tree state. Do not make review conclusions from the head branch alone.

Useful evidence includes:

```text
git status
git log --oneline --decorate --graph --all
git diff --stat BASE...HEAD
git diff --find-renames --find-copies BASE...HEAD
git diff BASE...HEAD -- path/to/feature.py
```

When GitHub data is available, inspect the pull request metadata, complete changed-file list, patch, comments, reviews, base commit, and head commit. If one endpoint is incomplete, use the commit comparison or file contents at both refs.

Preserve unrelated local changes. Review tooling must not reset, restore, or overwrite the user’s worktree.

### 3. Classify the diff by intent

Separate the change into:

- new behavior;
- moved code;
- renamed code;
- deleted code;
- changed contracts;
- changed imports;
- changed inheritance or composition;
- changed initialization;
- formatting or generated noise;
- tests and documentation.

This classification prevents a large movement diff from being incorrectly treated as a harmless no-op.

### 4. Measure traceability

Ask whether a reviewer can follow the old implementation into the new implementation without manually comparing two complete files.

Prefer:

- the same source file for local reorganization;
- small, contiguous extraction blocks;
- unchanged method bodies during a movement-only commit;
- no formatting changes during movement;
- one follow-up commit for architectural adaptation;
- explicit compatibility wrappers during transition.

Be cautious when:

- one file loses most of its implementation and another file is created almost entirely with additions;
- methods are moved and reformatted simultaneously;
- class inheritance changes at the same time as code movement;
- behavior changes are mixed into the extraction;
- reviewers must compare two entire files to understand the delta;
- the commit message claims “pure relocation” but adds new lifecycle or dependency behavior.

### 5. Inspect hidden contracts

For extracted classes, mixins, services, and adapters, inventory every dependency on `self` and every external symbol. Do not accept “independent” or “paradigm-agnostic” claims without checking the actual contract.

Look for dependencies on:

- fields initialized by the old owner;
- methods that remain in the old class;
- `super()` behavior;
- class attributes and descriptors;
- callbacks and generators;
- timers, queues, caches, and shared state;
- settings and persistence objects;
- native/game-thread dispatch guarantees;
- account or multibox scope;
- exception and fallback behavior.

A reusable mixin or service should document its required fields and methods, or expose a clear protocol/interface. If it still relies on many owner-specific methods, describe it as an owner-dependent mixin rather than an independent service.

### 6. Check construction and method resolution

Any change such as:

```python
class ExistingClass(NewMixin):
```

requires review even when `ExistingClass.__init__` is unchanged. Check:

- method resolution order;
- duplicate method names;
- `super()` calls;
- constructors and initialization order;
- class scanning or registration logic;
- type checks and `isinstance` assumptions;
- fallback and subclass behavior;
- public method availability;
- serialization or persistence assumptions.

An unchanged constructor does not prove an unchanged object lifecycle.

### 7. Verify claimed no-op behavior

For a claimed no-op refactor, require evidence proportional to the risk:

- compile/import validation;
- pyright/Pylance validation for changed modules;
- existing tests;
- focused before/after tests for moved public methods;
- constructor and lifecycle tests;
- method-set and signature comparison;
- call-path comparison;
- representative runtime smoke tests;
- no unexpected changes in logs, queues, settings, or native dispatch.

AST comparison is useful as supplemental evidence. It must not be the only evidence when file ownership, inheritance, initialization, or lifecycle changes.

### 8. Check whether the pull request is correctly scoped

A safe sequence commonly looks like this:

1. Preserve behavior and add tests around the existing implementation.
2. Reorganize code in place or perform a mechanical extraction with no formatting changes.
3. Verify the intermediate state.
4. Introduce the new abstraction or second consumer in a separate change.
5. Introduce behavior changes behind an explicit, tested adoption path.
6. Retire compatibility code only after consumers have migrated.

Do not combine all six stages into one “cleanup” pull request.

### 9. Verify default-off and opt-in claims literally

“Disabled by default” is not equivalent to “no-op when disabled.” Inspect the actual call path from the existing runtime entry point.

For an opt-in feature, verify that the disabled path does not unnecessarily:

- instantiate the feature controller;
- enumerate accounts or agents;
- read settings repeatedly;
- update caches, timers, breadcrumbs, or state machines;
- perform native or game-thread calls;
- alter shared-memory values;
- generate debug snapshots or overlays.

If the feature supports a diagnostic-only mode, such as an overlay while behavior is disabled, model the two paths explicitly:

```text
feature disabled + overlay disabled -> return before feature processing
feature disabled + overlay enabled  -> compute diagnostic state only
feature enabled                    -> compute and publish behavior
```

The review must compare the claimed disabled path with the actual call graph. A branch inside a deep controller method does not prove that the caller avoided the cost of constructing the controller, collecting inputs, or mutating state.

### 10. Review cross-cutting changes separately from the new feature

New feature code may be additive while its integration changes existing behavior. Identify edits to shared paths such as:

- generic follow or movement resolution;
- common UI drawing;
- shared-memory publishing;
- global settings;
- command dispatch;
- map and lifecycle handling;
- common utility functions.

Do not allow a new feature to hide unrelated behavioral changes behind its integration. If a general improvement is useful to the new feature, review it as a separate change unless the user explicitly accepts the expanded scope.

### 11. Verify every advertised integration path end to end

When documentation claims that a feature reports, receives, publishes, or synchronizes data, trace the entire path:

```text
producer -> transport or shared state -> receiver -> consumer -> observable effect
```

Check for:

- enum or command definitions;
- serialization and parameter shape;
- sender invocation;
- receiver dispatch;
- state update;
- consumer lookup;
- user-visible or runtime effect;
- retry and failure behavior.

A class that defines a reporter but is never instantiated is not an implemented integration. A command that is sent but absent from the enum or receiver is an incomplete path. Remove unsupported claims or complete the entire path before approval.

### 12. Check ownership and lifecycle transitions

Any feature that writes to shared state, flags, settings, caches, or overlays must define ownership and reset behavior.

Review transitions such as:

- feature disabled after being enabled;
- user input replacing an automatic value;
- map change;
- leader change;
- account or party change;
- publisher restart;
- stale or missing native data;
- exception during a partially completed write.

An ownership boolean alone is insufficient if it does not verify that the observed value still matches the value written by the feature. Automatic state must not overwrite a newer manual value merely because the feature previously owned the field.

### 13. Treat silent exception handling as a review risk

New integration code often uses broad `except Exception: pass` blocks around settings, native access, overlays, and shared-memory operations. These may prevent crashes, but they can also make a feature silently inactive and impossible to diagnose.

For every swallowed exception, ask:

- Is failure safe and intentional?
- Is there a diagnostic status or log?
- Can the user distinguish “feature inactive” from “feature failed”?
- Does partial state need to be rolled back?
- Is the exception hiding a missing binding, enum, or integration path?

Require at least one observable diagnostic path for important feature failures.

### 14. Do not add custom file-backed debuggers or persistence

The repository already provides approved interfaces for persistent data and runtime diagnostics. Pull requests must use those interfaces instead of creating ad-hoc file handlers.

Forbidden in feature or debugging changes unless explicitly authorized as a separate infrastructure project:

- custom `open()` calls for logs, state, or diagnostics;
- `os.makedirs()` or directory creation for feature-owned data;
- custom file-backed logger classes;
- direct writes through `Path.write_text()`, `Path.write_bytes()`, or equivalent;
- custom JSON or INI serialization;
- feature-specific log rotation, file naming, or retention systems.

Use the existing project mechanisms:

| Need | Approved mechanism |
| --- | --- |
| INI settings | `Settings` with the correct account or global scope |
| JSON data | The repository JSON factory and its approved storage scope |
| Immediate diagnostics | Console/runtime logging already provided by the project |
| Temporary in-memory history | A bounded runtime data structure with an explicit lifecycle |
| Native/UI diagnostics | Existing native bindings, UI logs, or approved diagnostic widgets |

If a new logging or persistence primitive is genuinely required, it must be its own infrastructure PR with an explicit design, lifecycle, scope, retention, failure, and privacy review. It must not be smuggled into an unrelated feature PR merely because the feature needs temporary debugging.

When reviewing a PR, search both the changed files and their new call paths for `open(`, `os.makedirs`, `Path.write`, `json.dump`, `configparser`, and custom logger names. A diagnostic claim does not authorize a new persistence mechanism.

### 15. Match static validation requirements to project tooling

Do not accept “compiles,” “pyflakes passes,” or “AST-identical” as a substitute for the project’s required checks.

For Python changes, pyright/Pylance is mandatory for the changed Python scope. Report the command, target, and result. A reviewer may accept pre-existing diagnostics when they are clearly separated from new diagnostics, but new type errors must be addressed or explicitly justified.

This review policy does not require behavioral test suites, runtime smoke tests, client-test matrices, or test evidence as a condition of approval. Do not add testing requirements to review comments when the task is a refactor or code review and the user has not specifically requested tests.

If a module is described as pure or offline-testable, inspect its imports. Imports of native-only modules, timers, settings, game enums, or runtime globals may prevent offline testing even when the algorithm itself is pure.

### 16. ImGui owns window persistence and state

For ImGui windows, ImGui is the owner of window persistence and window state. Feature code must not create competing persistence or positioning systems.

Custom window coordinate and status handlers are not permitted for ordinary ImGui windows, including custom storage of:

- position or screen coordinates;
- size or minimum-size enforcement through per-frame resets;
- collapsed or expanded state;
- visibility or open/closed state;
- focus, docking, or display status;
- manual restoration of saved window geometry.

Use the existing ImGui window API and its `ini_key`/persistence mechanism. Configure initial constraints only through the appropriate ImGui window flags or first-use APIs, and do not force those values again every frame. A feature may decide whether to call `Begin()` or whether a user-facing feature is enabled, but it must not fight ImGui over the window’s persistent state.

When reviewing UI changes, search for:

- custom `SetWindowPos`, `SetWindowSize`, `SetNextWindowPos`, or `SetNextWindowSize` calls;
- per-frame writes to window coordinates or dimensions;
- custom window classes that reposition or restore ordinary ImGui windows;
- separate INI/settings keys duplicating ImGui geometry or visibility;
- code that overwrites `p_open`, collapsed state, or window status after ImGui has evaluated it.

These are review blockers unless the window is explicitly a non-ImGui/native window with a documented ownership boundary. The review must identify the owner of each window’s geometry and persistence and reject multiple competing owners.

## New-feature review example: fight-zone positioning

PR #39 added a new fight-zone package, so its new files were not automatically a traceability violation. The guide identified a different set of issues:

- the advertised default-off path still instantiated and ticked the publisher;
- generic follow placement behavior changed in the same pull request;
- build-line reporting had a producer but no complete command or receive path;
- flag ownership did not reliably detect later manual overrides;
- publisher state was not clearly reset across map and lifecycle transitions;
- behavioral tests and pyright/Pylance validation were missing;
- broad exception handling could make the feature fail silently.

This example demonstrates that the review must evaluate both source traceability and runtime integration. A new package may be structurally appropriate while its integration still violates no-op, lifecycle, scope, or verification requirements.

## Scope review example: Skills Unlocker diagnostics

PR #47 added a custom `SessionLogger` that created `Logs/Sessions` and wrote diagnostic files through `open()` and `os.makedirs()`. This violated both scope and repository policy:

- the PR’s primary scope was Skills Unlocker route behavior;
- the logger was reusable infrastructure;
- generic agent-interaction code was instrumented outside the feature;
- custom file-backed diagnostics bypassed the project’s approved interfaces.

The correct review action is to remove the custom logger from the feature PR. Use existing console or runtime diagnostics for the feature, or create a separate infrastructure proposal if persistent diagnostics are truly needed.

## Common red flags

### Large deletion plus large new-file addition

This often indicates a rewrite or an extraction that Git cannot represent usefully. Ask the author to preserve recognizable code boundaries and separate movement from adaptation.

### New initialization helper that is not used by the current owner

This creates a second lifecycle contract. Either keep initialization in the current owner until the second consumer exists, or explicitly migrate both consumers and test initialization order.

### A service claims independence but calls owner-specific methods

This is hidden coupling. Require a documented protocol, a narrow adapter, or a more accurate architectural description.

### “No behavior change” while changing inheritance

Inheritance changes can affect MRO, `super()`, subclass discovery, type checks, and method collisions. Treat this as a structural risk, not a textual change.

### Formatting mixed with movement

Formatting destroys line-level history and makes semantic review harder. Request a separate formatting change, or defer formatting until after the migration is verified.

### Unrelated bug fixes in an extraction

They make rollback and regression analysis ambiguous. Move them to a separate pull request.

### A new parallel implementation is introduced before the old one is retired

This can create two sources of truth. Require an explicit compatibility strategy and a retirement plan.

## AI-oriented review instructions

When asking another AI agent to review a pull request, provide these instructions:

```text
Review this pull request against the repository’s traceable-migration policy.

The primary objective is to preserve behavior and source traceability. Do not assume that a large movement diff is safe because the author calls it a relocation or because AST comparison passes.

First establish the base and head revisions. Then inventory changed files, additions, deletions, renames, inheritance changes, initialization changes, public API changes, and behavior changes.

Classify the pull request as additive, mechanical relocation, structural refactor, semantic change, or rewrite. State which classification is supported by the actual diff.

Compare the implementation against the user’s vision:

- Is the original implementation still recognizable?
- Can Git and a human reviewer follow the change without comparing two complete files manually?
- Were movement, architecture, formatting, and behavior changes separated?
- Did inheritance or composition change?
- Did initialization order or lifecycle change?
- Does a new service actually have an explicit dependency contract?
- Are old APIs and call paths preserved?
- Are settings, persistence, callbacks, queues, and native dispatch contracts unchanged?
- Are tests and pyright/Pylance checks sufficient for the changed scope?

Do not modify the repository. Produce evidence-backed findings with file paths and line references. Separate blockers, requested changes, risks, and positive evidence.

If the change violates traceability, recommend a smaller sequence of commits. Prefer same-file reorganization when practical. If a new file is required, recommend a mechanical movement stage followed by separate architecture and behavior stages.
```

## Feedback template

Use this structure when writing review feedback for the author or for a follow-up AI agent:

```text
Request changes: [short reason].

What the diff actually does:
- [file and approximate change size]
- [new/deleted classes or inheritance changes]
- [behavioral or lifecycle changes]

Why this conflicts with the requested scope:
- [traceability problem]
- [reviewability or rollback problem]
- [hidden dependency or contract problem]

Required direction:
1. [smallest acceptable first step]
2. [verification required for that step]
3. [separate follow-up for architecture or behavior]

Acceptance criteria:
- Existing behavior and public contracts are preserved.
- The original implementation remains recognizable.
- Git can show the movement or reorganization clearly.
- No unrelated formatting or bug fixes are included.
- Initialization, MRO, lifecycle, and dependency contracts are explicit.
- Relevant tests and pyright/Pylance checks pass.
```

## Case study: combat-service extraction

The review of PR #34 is a useful example of the distinction between runtime equivalence and traceable change.

The pull request presents itself as a pure relocation of combat utilities from `BuildMgr.py` into `combat_services.py`. The method-body preservation claims and compile checks are useful positive evidence. However, the diff removes most of the implementation from the original file, recreates it in a new file, changes `BuildMgr` inheritance, and introduces a second initialization contract.

The correct review conclusion is not necessarily “the code is behaviorally wrong.” The correct conclusion is that the change is too structurally broad for a traceable no-op migration. The requested remedy is to split movement, abstraction, and behavior-tree integration into independently reviewable stages, while keeping the source recognizable and documenting the actual dependency contract.

## Review record to append after each analysis

For future pull requests, add a short record containing:

- PR number and title;
- base and head commits;
- requested user vision;
- actual diff classification;
- changed-file and line-count summary;
- traceability assessment;
- hidden-contract findings;
- validation performed;
- blockers and required decomposition;
- accepted exceptions to this guide and why.

This record allows later reviews to enrich the guide with project-specific patterns instead of repeating the same analysis from scratch.
