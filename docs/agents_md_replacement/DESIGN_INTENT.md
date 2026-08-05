# Replacement Instruction System - Design Intent

## Purpose

These files are an AI context and behavior layer for Py4GW development. They are not ordinary human-facing project documentation and they do not replace the underlying coding harness or its tooling.

## Intended Construction

- Use the structure and feature vocabulary of mature public harness prompts, especially the Codex and OpenCode source files stored under `sources/`.
- Combine that structure with the actual Py4GW knowledge already present in `AGENTS.md`, `CLAUDE.md`, `.opencode`, `.codex`, `.claude`, project documentation, and related repositories.
- Preserve source material and provenance so the user can decide what remains, changes, or is removed.
- Prefer context density and model-relevant instruction over prose optimized primarily for human readability.
- Avoid inventing architecture, behavior, or rules when the available sources do not establish them.

## Parallel Drafts

- `AGENTS_merged_sources.md` is the generic merged-source version based on the public Codex and OpenCode files.
- `AGENTS_py4gw.md` is the Py4GW-adapted version, combining the same structural basis with the project's actual domain context.
- The live project instruction files remain separate and must not be silently replaced while these drafts are being developed.

## Working Process

- Develop and refine the Py4GW version in `Py4GW_Reforged` first.
- After the Reforged version is finalized, transfer the appropriate result to `Py4GW_Reforged_Native`.
- Build the replacement section by section, beginning with `Identity and Role`.
- Treat the user as the final authority on inclusion, exclusion, wording, and priority.
- Keep the source files available locally under `sources/` for continual reference.

## Identity-and-Role Intent

The first section should establish the agent as `ApoBot`, a custom Py4GW helper; define the Reforged and native-project context; describe the agent's investigation, implementation, verification, review, and documentation role; require didactical grounded explanations; require active prompt-context enrichment; and distinguish verified facts, interpretations, assumptions, proposed changes, and unresolved questions.
