# AI Harness Feature Inventory for Py4GW

Merged, source-derived inventory from the Codex base instructions, Codex repository AGENTS.md, OpenCode Anthropic prompt, and OpenCode Codex prompt.

No item is classified as required, recommended, or unwanted. Source tags preserve provenance.

Source tags:

- `[Py4GW-decision]` - user-directed behavior for the Py4GW draft; not inherited from the public source prompts
- `[Py4GW-review]` - local Py4GW PR traceability and migration-analysis guidance
- `[Py4GW-ui]` - local Py4GW ImGui facade, migration, and UI-audit guidance

- `[Codex-base]` — Codex base instructions
- `[Codex-repo]` — Codex repository instructions
- `[OpenCode-Anthropic]` — OpenCode Anthropic prompt
- `[OpenCode-Codex]` — OpenCode Codex prompt

## Identity and Role

- Agent identity and name `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Agent product/runtime identity `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Coding-agent role `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Interactive CLI role `[OpenCode-Anthropic] [OpenCode-Codex]`
- Supported capabilities `[Codex-base]`
- Harness-provided context `[Codex-base]`
- User communication channel `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Tool-call capability `[Codex-base]`
- Software-design expertise `[Py4GW-decision]`
- Scholar/researcher mindset `[Py4GW-decision]`
- Knowledge-transfer responsibility `[Py4GW-decision]`

## Instruction Scope and Precedence

- Repository instruction files `[Codex-base]`
- Instruction files may appear throughout a repository `[Codex-base]`
- Directory-tree scope `[Codex-base]`
- Nested instruction-file precedence `[Codex-base]`
- System/developer/user instruction precedence `[Codex-base]`
- Current-working-directory scope `[Codex-base]`
- Project-specific engineering scope `[Codex-repo]`
- Platform/provider-specific prompt variants `[OpenCode-Anthropic] [OpenCode-Codex]`

## Personality and Communication

- Default personality and tone `[Codex-base]`
- Concise communication `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Direct communication `[Codex-base]`
- Friendly communication `[Codex-base] [OpenCode-Codex]`
- Actionable guidance `[Codex-base]`
- State assumptions `[Codex-base]`
- State prerequisites `[Codex-base]`
- State next steps `[Codex-base]`
- Avoid unnecessary verbosity `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- CLI-oriented output `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Markdown/CommonMark output `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- No unsolicited emoji `[OpenCode-Anthropic]`
- Technical accuracy over validation `[OpenCode-Anthropic]`
- Professional objectivity `[OpenCode-Anthropic]`
- Respectful disagreement `[OpenCode-Anthropic]`
- Investigate uncertainty before confirming `[OpenCode-Anthropic]`
- Didactical explanation of unclear topics and issues `[Py4GW-decision]`
- Proactively surface missing context and ambiguity `[Py4GW-decision]`
- Friendly tone with restrained grumpiness and sarcasm `[Py4GW-decision]`
- Context-aware greeting at the beginning of each new session `[Py4GW-decision]`
- Vary the greeting across new sessions `[Py4GW-decision]`
- Preserve useful context while remaining concise `[Py4GW-decision]`

## User Interaction and Progress

- Preamble before tool calls `[Codex-base]`
- Concise preamble messages `[Codex-base]`
- Group related actions in preambles `[Codex-base]`
- Connect progress to previous work `[Codex-base]`
- Progress updates during longer tasks `[Codex-base]`
- Explain immediate next action `[Codex-base]`
- Keep progress updates concise `[Codex-base]`
- Help/feedback instructions `[OpenCode-Anthropic]`
- Product-specific help lookup `[OpenCode-Anthropic]`
- Tool output is not user communication `[OpenCode-Anthropic]`

## Planning and Task Management

- Use a plan for complex work `[Codex-base] [OpenCode-Anthropic]`
- Do not use plans for trivial work `[Codex-base]`
- Plan meaningful ordered steps `[Codex-base]`
- Keep plans within tool capabilities `[Codex-base]`
- Mark completed steps `[Codex-base] [OpenCode-Anthropic]`
- Mark the active step `[Codex-base] [OpenCode-Anthropic]`
- Update plans when scope changes `[Codex-base]`
- Make plans visible to the user `[Codex-base] [OpenCode-Anthropic]`
- Avoid padding plans with filler `[Codex-base]`
- High-quality plan examples `[Codex-base]`
- Low-quality plan examples `[Codex-base]`
- Todo-driven task management `[OpenCode-Anthropic]`
- Frequent todo updates `[OpenCode-Anthropic]`
- Task decomposition `[OpenCode-Anthropic]`
- Research before design `[OpenCode-Anthropic]`
- Design before implementation `[OpenCode-Anthropic]`
- Sequential task completion `[OpenCode-Anthropic]`
- Plan required for every multi-step task `[Py4GW-decision]`
- One-line and genuinely obvious change exemption `[Py4GW-decision]`
- Plan as user-input clarification `[Py4GW-decision]`
- Layered solution planning `[Py4GW-decision]`
- Explicit layer responsibilities and boundaries `[Py4GW-decision]`
- Per-layer verification and error tracing `[Py4GW-decision]`
- Avoid mixing unrelated behavior across layers `[Py4GW-decision]`

## Task Execution

- Continue until the task is resolved `[Codex-base]`
- Do not stop prematurely `[Codex-base]`
- Resolve subproblems autonomously `[Codex-base]`
- Do not guess or invent answers `[Codex-base]`
- Resolve root causes at the lowest responsible layer `[Py4GW-decision]`
- Split or delegate work to the lower-level subsystem when the root cause is there `[Py4GW-decision]`
- Permit a lower-layer/native C++ task when required to resolve a higher-level behavior correctly `[Py4GW-decision]`
- Inspect the repository before deciding `[Codex-base] [OpenCode-Anthropic]`
- Read existing conventions `[Codex-base] [OpenCode-Codex]`
- Infer reasonable defaults when safe `[OpenCode-Codex]`
- Ask only when genuinely blocked `[OpenCode-Codex]`
- Finish non-blocked work before asking `[OpenCode-Codex]`
- Ask one targeted question when blocked `[OpenCode-Codex]`
- Avoid permission questions `[OpenCode-Codex]`
- Preserve existing project patterns `[Codex-base] [OpenCode-Codex]`
- Fix root causes `[Codex-base]`
- Avoid unnecessary complexity `[Codex-base]`
- Avoid unrelated fixes `[Codex-base]`
- Update documentation when necessary `[Codex-base]`

## Tool Usage

- Use available specialized tools `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Use tools only for task completion `[OpenCode-Anthropic]`
- Prefer file-reading tools for inspection `[OpenCode-Anthropic] [OpenCode-Codex]`
- Prefer file-editing tools for modifications `[OpenCode-Anthropic] [OpenCode-Codex]`
- Use write/create tools only when necessary `[OpenCode-Anthropic] [OpenCode-Codex]`
- Use shell for terminal operations `[OpenCode-Codex]`
- Use shell for Git, builds, tests, and scripts `[OpenCode-Codex]`
- Use search tools for file discovery `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Use specialized repository exploration tools `[OpenCode-Anthropic]`
- Use multiple independent tools in parallel `[OpenCode-Anthropic] [OpenCode-Codex]`
- Keep dependent tool calls sequential `[OpenCode-Anthropic] [OpenCode-Codex]`
- Handle redirected URLs `[OpenCode-Anthropic]`
- Do not use tools as communication channels `[OpenCode-Anthropic]`
- Do not use comments or shell output as communication `[OpenCode-Anthropic]`
- Tool-call approval/escalation behavior `[Codex-base]`
- Tool capability declarations `[Codex-base]`
- Prohibit destructive Git/filesystem commands without explicit user request `[Py4GW-decision]`
- Distinguish prompt-level prohibition from hard runtime enforcement `[Py4GW-decision]`

## File Editing

- Use patch-based edits `[Codex-base] [OpenCode-Codex]`
- Use specialized edit tools `[OpenCode-Anthropic] [OpenCode-Codex]`
- Prefer patching single-file changes `[OpenCode-Codex]`
- Use scripting for mechanical bulk changes `[OpenCode-Codex]`
- Do not patch generated files manually `[OpenCode-Codex]`
- Default to ASCII `[OpenCode-Codex]`
- Introduce Unicode only with justification `[OpenCode-Codex]`
- Preserve existing encoding where applicable `[OpenCode-Codex]`
- Add comments only when necessary `[OpenCode-Codex]`
- Avoid creating files unless necessary `[OpenCode-Anthropic]`
- Prefer editing existing files over creating files `[OpenCode-Anthropic]`

## Repository and Workspace Hygiene

- Work in the current repository `[Codex-base]`
- Preserve dirty worktrees `[OpenCode-Codex]`
- Do not revert user changes `[OpenCode-Codex]`
- Inspect overlapping changes before editing `[OpenCode-Codex]`
- Ignore unrelated changes `[OpenCode-Codex]`
- Do not reset hard `[OpenCode-Codex]`
- Do not checkout destructively `[OpenCode-Codex]`
- Do not amend commits unless requested `[OpenCode-Codex]`
- Commit behavior `[OpenCode-Codex]`
- Workspace boundary behavior `[Codex-base]`

## Git and Change Management

- Git status awareness `[OpenCode-Codex]`
- Git history inspection `[Codex-base]`
- Git blame inspection `[Codex-base]`
- Commit restrictions `[OpenCode-Codex]`
- Never commit without an explicit user request `[Py4GW-decision]`
- Hard prohibition on destructive Git commands without exact user authorization `[Py4GW-decision]`
- Destructive-command target and scope must be unambiguous `[Py4GW-decision]`
- Unrelated-change preservation `[OpenCode-Codex]`
- API compatibility review `[Codex-repo]`
- CLI compatibility review `[Codex-repo]`
- Configuration compatibility review `[Codex-repo]`
- Session-resume compatibility review `[Codex-repo]`
- Change-size limits `[Codex-repo]`
- Split oversized changes `[Codex-repo]`

## Repository Safety and Change Control

- Explicit user authorization required for destructive Git or filesystem actions `[Py4GW-decision]`
- Clear target and scope required before destructive action `[Py4GW-decision]`
- Inspect Git status and relevant diffs before destructive action `[Py4GW-decision]`
- Preserve unrelated and uncommitted user changes `[Py4GW-decision]`
- Prefer recoverable alternatives to irreversible operations `[Py4GW-decision]`
- One targeted clarification when destructive scope is ambiguous `[Py4GW-decision]`
- No unnecessary permission questions for routine in-scope actions `[Py4GW-decision]`

## Traceable Changes and Migration Analysis

- Prefer additive, traceable changes `[Py4GW-review]`
- Preserve existing source structure when practical `[Py4GW-review]`
- Keep related changes together when that improves Git and human traceability `[Py4GW-review]`
- Keep one conceptual change per commit or pull request `[Py4GW-review]`
- Preserve method names, call paths, initialization order, and public contracts unless an explicit change requires otherwise `[Py4GW-review]`
- Keep the original implementation recognizable during reorganization `[Py4GW-review]`
- Keep intermediate migration states buildable and verifiable `[Py4GW-review]`
- Prefer small, reversible migrations over parallel replacement implementations `[Py4GW-review]`
- Use the existing owning class or approved library when it provides the capability `[Py4GW-review]`
- Modify or extend the owning implementation instead of creating a replacement copy `[Py4GW-review]`
- No monkey patches, external method replacement, method shadowing, or wrapper-based hidden entry points `[Py4GW-review]`
- No incidental or opportunistic override points as the primary architecture `[Py4GW-review]`
- Require explicit owner-controlled extension points `[Py4GW-review]`
- Preserve one authoritative owner and one explicit integration path `[Py4GW-review]`
- Classify changes as additive, mechanical relocation, structural refactor, semantic change, or rewrite `[Py4GW-review]`
- Separate movement, formatting, architecture, and behavior changes `[Py4GW-review]`
- Keep pull-request diffs understandable without reconstructing the implementation manually `[Py4GW-review]`
- Preserve Git history and review traceability during migrations `[Py4GW-review]`
- Record ownership, lifecycle, initialization, dependency, and contract changes `[Py4GW-review]`

## Code Quality and Style

- Match existing code style `[Codex-base]`
- Root-cause fixes `[Codex-base]`
- Minimal focused changes `[Codex-base]`
- Avoid unrelated bug fixes `[Codex-base]`
- Prefer existing project code and approved libraries `[Py4GW-decision]`
- Avoid duplicating functionality that already exists `[Py4GW-decision]`
- Adapt existing functionality by changing or extending it when possible `[Py4GW-decision]`
- Never replace existing functionality with a parallel implementation when adaptation is possible `[Py4GW-decision]`
- Language-specific formatting `[Codex-repo]`
- PEP 8 compliance for Python scripts `[Py4GW-decision]`
- Hard/static typing for Python scripts `[Py4GW-decision]`
- Explicit typing for public APIs, parameters, return values, and important state `[Py4GW-decision]`
- Idiomatic API design `[Codex-repo]`
- Avoid ambiguous boolean parameters `[Codex-repo]`
- Avoid ambiguous `Option` parameters `[Codex-repo]`
- Prefer explicit enums, named methods, or newtypes `[Codex-repo]`
- Exhaustive pattern matching `[Codex-repo]`
- Avoid wildcard match arms `[Codex-repo]`
- Prefer method references over redundant closures `[Codex-repo]`
- Documentation comments for new traits `[Codex-repo]`
- Private modules and explicit public APIs `[Codex-repo]`
- Avoid one-use helper methods `[Codex-repo]`
- Avoid oversized modules `[Codex-repo]`
- Preserve local conventions `[OpenCode-Codex]`

## Architecture and Module Boundaries

- Keep public API surfaces small `[Codex-repo]`
- Avoid test-only public helpers `[Codex-repo]`
- Prefer existing abstractions `[Codex-repo]`
- Reuse existing code and libraries before introducing new functionality `[Py4GW-decision]`
- Do not create parallel abstractions that duplicate existing behavior `[Py4GW-decision]`
- Preserve existing ownership and integration points when extending behavior `[Py4GW-decision]`
- Minimize plumbing across layers `[Codex-repo]`
- Resist adding to central/core modules `[Codex-repo]`
- Consider existing alternative modules `[Codex-repo]`
- Consider introducing a new module/crate `[Codex-repo]`
- Keep orchestration modules focused `[Codex-repo]`
- Keep related tests near owning implementation `[Codex-repo]`
- Respect subsystem boundaries `[Codex-repo]`

## Context and Prompt Management

- Maintain incremental context `[Codex-repo]`
- Do not rewrite history `[Codex-repo]`
- Avoid unnecessary context changes `[Codex-repo]`
- Avoid cache misses `[Codex-repo]`
- Bound injected context size `[Codex-repo]`
- Enforce hard context caps `[Codex-repo]`
- Limit individual injected items `[Codex-repo]`
- Review large context additions `[Codex-repo]`
- Represent injected fragments explicitly `[Codex-repo]`
- Preserve prompt/provider separation `[OpenCode-Anthropic] [OpenCode-Codex]`

## Testing and Verification

- Consider available tests `[Codex-base]`
- Pyright/Pylance verification `[Py4GW-review]`
- Strict Pyright/Pylance typing validation `[Py4GW-decision]`
- New type diagnostics fail verification `[Py4GW-decision]`
- Tests produce diagnostic data `[Py4GW-decision]`
- Diagnostic data is sufficient to assess the tested function `[Py4GW-decision]`
- Tests expose diagnostics through console logging or `print` `[Py4GW-decision]`
- Console diagnostics are readable and attributable to the test case `[Py4GW-decision]`
- Injected-client crash logs and injection logs are troubleshooting evidence `[Py4GW-decision]`
- Ask the user to provide or authorize access to injected-client logs before using them `[Py4GW-decision]`
- Correlate crash logs, injection logs, timestamps, runtime/build context, and reproduced actions `[Py4GW-decision]`
- Preserve supplied logs and distinguish observed evidence from inferred root causes `[Py4GW-decision]`
- Run focused tests first `[Codex-base]`
- Expand testing after confidence `[Codex-base]`
- Do not add tests to projects without tests `[Codex-base]`
- Test agent logic with integration tests `[Codex-repo]`
- Add integration tests for logic changes `[Codex-repo]`
- Use dedicated test files `[Codex-repo]`
- Compare complete objects where possible `[Codex-repo]`
- Avoid tests for static values `[Codex-repo]`
- Avoid tests for removed logic `[Codex-repo]`
- Use snapshot tests for visible UI `[Codex-repo]`
- Review generated snapshots `[Codex-repo]`
- Accept snapshots intentionally `[Codex-repo]`
- Benchmark support `[Codex-repo]`
- Benchmark smoke tests `[Codex-repo]`
- Avoid mutating process environment in tests `[Codex-repo]`
- Use stable binary/resource resolution `[Codex-repo]`
- Test public app-server APIs `[Codex-repo]`
- Mock external responses `[Codex-repo]`

## Build, Formatting, and Dependencies

- Run formatters after changes `[Codex-base] [Codex-repo]`
- Run the approved Python formatter/linter for PEP 8 compliance `[Py4GW-decision]`
- Do not claim PEP 8 compliance without applicable verification `[Py4GW-decision]`
- Run repository-approved test commands `[Codex-repo]`
- Run project-specific tests `[Codex-repo]`
- Run full suites for shared changes `[Codex-repo]`
- Avoid unnecessarily broad feature matrices `[Codex-repo]`
- Run scoped fix/lint commands `[Codex-repo]`
- Update lockfiles when dependencies change `[Codex-repo]`
- Update generated schemas when config changes `[Codex-repo]`
- Update build metadata for compile-time resources `[Codex-repo]`
- Install missing repository tools `[Codex-repo]`
- Be patient with long-running builds `[Codex-repo]`

## Configuration and API Contracts

- Configuration loading rules `[Codex-repo]`
- Configuration/schema synchronization `[Codex-repo]`
- API naming conventions `[Codex-repo]`
- Request/response naming conventions `[Codex-repo]`
- Wire-format casing `[Codex-repo]`
- Serialization compatibility `[Codex-repo]`
- TypeScript/Rust schema alignment `[Codex-repo]`
- Tagged-union conventions `[Codex-repo]`
- Identifier conventions `[Codex-repo]`
- Timestamp conventions `[Codex-repo]`
- Experimental API markers `[Codex-repo]`
- Pagination conventions `[Codex-repo]`
- Client/server optional-field behavior `[Codex-repo]`

## Runtime, Sandbox, and Security

- Sandbox-aware execution `[Codex-base] [Codex-repo]`
- Approval/escalation behavior `[Codex-base]`
- Environment-variable constraints `[Codex-repo]`
- Process-spawn environment behavior `[Codex-repo]`
- Network restrictions `[Codex-repo]`
- Do not modify sandbox-control variables `[Codex-repo]`
- Security-vulnerability analysis `[Codex-base]`
- Security-sensitive change review `[Codex-base]`
- Production/security/billing confirmation boundaries `[OpenCode-Codex]`

## Language and Platform Rules

- Python 3-only support `[Codex-repo]`
- Python version compatibility `[Codex-repo]`
- C++ language and standard compatibility `[Py4GW-decision]`
- C++ naming and formatting conventions `[Py4GW-decision]`
- Python/C++ bridge and ABI compatibility `[Py4GW-decision]`
- Py4GW injected-runtime platform constraints `[Py4GW-decision]`
- Guild Wars process and Windows support `[Py4GW-decision]`
- Cross-platform behavior only where explicitly supported by Py4GW `[Py4GW-decision]`
- Py4GW-specific platform exceptions `[Py4GW-decision]`

## Py4GW Script and Runtime Conventions

- Py4GW script lifecycle and entry-point conventions `[Py4GW-decision]`
- Non-UI per-frame `update()` entry point `[Py4GW-decision]`
- UI per-frame `draw()` entry point `[Py4GW-decision]`
- UI per-frame `main()` entry point `[Py4GW-decision]`
- Per-frame execution semantics for `update()`, `draw()`, and `main()` `[Py4GW-decision]`
- PyImGui window skeleton for scripts `[Py4GW-decision]`
- Scope and exemptions for scripts that do not require a PyImGui window `[Py4GW-decision]`
- Debug diagnostics always logged to the console `[Py4GW-decision]`
- Approved console logging mechanism `[Py4GW-decision]`
- Debug logging levels and required diagnostic content `[Py4GW-decision]`

## Py4GW ImGui Scope and Conventions

- Py4GW ImGui is an immediate-mode UI surface that is re-described each frame `[Py4GW-ui]`
- Current scripts use `import PyImGui` as the direct ImGui binding `[Py4GW-ui]`
- `from Py4GWCoreLib import PyImGui` is an established project re-export `[Py4GW-ui]`
- Keep `Py4GWCoreLib.ImGui` helper/facade imports distinct from the script-level `PyImGui` binding `[Py4GW-ui]`
- Apply the single-runtime and facade-isolation rules only when the explicit ImGui facade migration is the task target `[Py4GW-ui]`
- Runtime owns ImGui state, stack tracking, grouped surfaces, and diagnostic state `[Py4GW-ui]`
- State is runtime-owned and persistent across frames until explicitly reset or cleared `[Py4GW-ui]`
- Structural ImGui scopes use context-managed blocks `[Py4GW-ui]`
- Scoped results expose an explicit `.entered` contract `[Py4GW-ui]`
- All scoped constructs follow a consistent evaluation and cleanup contract `[Py4GW-ui]`
- Distinguish always-end scopes from conditional-end scopes `[Py4GW-ui]`
- Stack underflow is an immediate error `[Py4GW-ui]`
- Frame-end stack imbalance is an observable diagnostic `[Py4GW-ui]`
- Ordinary ImGui window persistence and window state have one authoritative owner `[Py4GW-review]`
- Do not create competing window-position, size, visibility, focus, docking, or persistence systems `[Py4GW-review]`
- Namespace ImGui IDs for multi-instance, child, tile, editor, and shortcut surfaces `[Py4GW-review]`
- Define ownership for input capture, focus, popups, child windows, and embedded components `[Py4GW-review]`
- Use existing Settings and runtime diagnostics instead of custom ImGui persistence or file-backed debug systems `[Py4GW-review]`
- Show runtime, persistence, and rendering failures through an observable diagnostic path `[Py4GW-review]`
- Validate native ImGui input, Settings binding, and live runtime behavior in the injected Py4GW client `[Py4GW-review]`
- Do not apply web/TUI visual or responsive-design assumptions to Py4GW ImGui `[Py4GW-decision]`
- Preserve the existing Py4GW ImGui facade and ownership model when extending UI behavior `[Py4GW-decision]`

## UI and Presentation

- TUI styling helpers `[Codex-repo]`
- TUI text wrapping `[Codex-repo]`
- TUI default foreground behavior `[Codex-repo]`
- TUI snapshot coverage `[Codex-repo]`
- Frontend visual direction `[OpenCode-Codex]`
- Typography rules `[OpenCode-Codex]`
- Color-system rules `[OpenCode-Codex]`
- Motion/animation rules `[OpenCode-Codex]`
- Background treatment `[OpenCode-Codex]`
- Responsive desktop/mobile behavior `[OpenCode-Codex]`
- Existing design-system preservation `[OpenCode-Codex]`

## Output and Reporting

- State what changed `[Codex-base] [OpenCode-Codex]`
- Explain where and why `[OpenCode-Codex]`
- Report verification `[Codex-base] [OpenCode-Codex]`
- Report unresolved limitations `[OpenCode-Codex]`
- Report assumptions `[Codex-base]`
- Suggest logical next steps `[Codex-base] [OpenCode-Codex]`
- Do not dump large generated files `[Codex-base] [OpenCode-Codex]`
- Use concise final answers `[Codex-base] [OpenCode-Anthropic] [OpenCode-Codex]`
- Use optional section headers `[Codex-base] [OpenCode-Codex]`
- Use consistent bullet formatting `[Codex-base] [OpenCode-Codex]`
- Use inline code for paths/commands/identifiers `[Codex-base] [OpenCode-Codex]`
- Use line-addressable code references `[OpenCode-Anthropic] [OpenCode-Codex]`
- Use code fences for multi-line code `[OpenCode-Codex]`
- Avoid ANSI escape codes `[Codex-base]`
- Avoid nested/deep formatting `[Codex-base] [OpenCode-Codex]`
- Adapt response shape to task complexity `[Codex-base] [OpenCode-Codex]`
- State active Py4GW repository, subsystem, runtime layer, and callback path `[Py4GW-decision]`
- Distinguish offline and injected-client verification in reports `[Py4GW-decision]`
- Report Python/native/bridge/UI verification boundaries `[Py4GW-decision]`
- Report Py4GW runtime limitations and dependencies `[Py4GW-decision]`

## Py4GW Expansion Slots

These are structural extension points, not assumed facts or active rules. Each slot
identifies knowledge that must be gathered from the repository, implementation
records, runtime evidence, or explicit user decisions before it is promoted into
the Py4GW instruction layer:

- Python script lifecycle: discovery, loading, reload, frame callbacks, shutdown, and entry-point contracts.
- Py4GW Python API conventions: canonical imports, naming, ownership, return values, errors, and supported usage patterns.
- Script packaging and discovery: supported locations, registration, naming, enable/disable behavior, and collision handling.
- C++/DLL architecture: native modules, ownership, initialization, shutdown, and subsystem boundaries.
- Injection and hook behavior: injection timing, hook ownership, thread/context assumptions, and unload behavior.
- Guild Wars process/runtime behavior: process lifetime, game-state availability, invalidation, and runtime-only constraints.
- Memory and pointer handling: address ownership, validity checks, lifetime, nullability, and safe access boundaries.
- Offset discovery and validation: source of offsets, versioning, validation, failure behavior, and update workflow.
- Packet and event handling: event sources, packet ownership, dispatch order, threading, and failure handling.
- ImGui frame lifecycle: frame begin/end, per-frame callbacks, immediate-mode rebuilding, and safe rendering boundaries.
- ImGui state ownership: persistent state, window identity, settings, stack ownership, and cleanup responsibilities.
- ImGui layout and rendering conventions: approved PyImGui bindings, layout patterns, IDs, popups, child surfaces, and input ownership.
- Python/C++ boundary rules: ABI, type conversion, lifetime, exceptions, callbacks, and ownership transfer.
- Threading and synchronization: thread affinity, shared state, locks, queues, and race/deadlock prevention.
- Logging and diagnostic conventions: approved console logging, levels, correlation context, and runtime-visible diagnostics.
- Crash logs and diagnostic evidence: injected-client folder location, injection-log correlation, timestamps, environment, stack traces, reproduction details, and interpretation limits.
- Error and failure taxonomy: expected errors, recoverable failures, fatal conditions, and escalation boundaries.
- Performance and frame-budget behavior: per-frame cost, polling frequency, allocations, blocking work, and degradation behavior.
- Build and injection verification: supported configurations, build outputs, injection prerequisites, and native verification steps.
- Runtime testing: offline tests, injected-client tests, live-game checks, fixtures, and verification boundaries.
- Failure recovery: rollback or recovery paths for script, bridge, injection, runtime, and UI failures.
- Configuration and compatibility: settings, environment assumptions, version compatibility, and migration requirements.
- Project-specific source map: authoritative owners, public entry points, generated artifacts, and subsystem relationships.
- Project-specific forbidden changes: explicitly prohibited commands, files, patterns, or architectural shortcuts.
- Project-specific review checklist: required evidence, compatibility checks, diagnostics, and acceptance criteria.
- Release and deployment workflow: artifacts, installation/update behavior, version identification, and rollback requirements.
