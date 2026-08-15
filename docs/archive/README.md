# Retired Documentation Archive

Status: historical material. This folder is the single home for every document
retired from the live `docs/` tree. Nothing here is current runtime or design
authority; live knowledge lives in the topic folders under `../`.

Everything was moved with `git mv`, so file history is preserved. Use this
index for the assessment pass: each file carries a tag saying why it was
retired.

**Tags:** `superseded` (replaced by newer work), `abandoned` (the work was
dropped), `completed` (the plan/handover's work shipped), `placeholder`
(stub with no content), `duplicate` (content lives elsewhere), `capture`
(transient generated output), `generated` (derived data, reproducible),
`broken` (reads code that no longer exists), `stale tool` (answered scratch
script).

## Architecture

- `architecture/reference/py4-gw-model-features-detail.txt` — plain-text quick-scan export; the canonical model is `../architecture/reference/py4-gw-conceptual-model.md`. *(generated)*

## Bridge

- `bridge/shared-memory/multibox-shmem-cpp-writer-plan.md` — C++ shmem-writer migration plan; implemented and working. The postmortem at `../bridge/shared-memory/multibox-shmem-cpp-writer-postmortem.md` is the layout authority (its `ATTRIBUTES` count corrects this plan). *(completed)*

## Game client

- `game-client/research/cpp-wasm-mapping-backup.md` — empty cataloger placeholder. *(placeholder)*
- `game-client/research/handover-backup.md` — empty placeholder; the handover content was absorbed into the live subsystem records. *(placeholder)*
- `game-client/research/map-travel-reverse-engineering-backup.md` — stub noting the content is identical to the live original. *(placeholder)*
- `game-client/research/player-skill-system-callable-functions.md` — skill-execution address catalog, duplicated in `../game-client/research/gw-combat-ai-reverse-engineering.md` and `reverse-engineering-reference.md`. *(duplicate)*

## Items / modifiers

- `items/modifiers/comparison-and-painpoints.md` — redesign rationale for the removed `item_mods_src`; the open gaps were resolved by the shipped `Item.Mods` API. *(superseded)*
- `items/modifiers/current-python-system.md` — the removed `Py4GWCoreLib/item_mods_src/` system end-to-end. *(superseded)*
- `items/modifiers/mod-system-research.md` — research plus the earlier proposed enum design, superseded by `item-mods-design.md`. *(superseded)*
- `items/modifiers/mod_defs_sketch.py` — proposal sketch; the final system was not built as sketched. *(superseded)*
- `items/modifiers/generated/mod-naming-audit.txt` — naming-audit capture; the 17 unnamed modids are resolved in `../items/modifiers/tools/game-mod-table-named.txt`. *(capture)*
- `items/modifiers/generated/single-item-dump.txt` — captured sample of one item dump. *(capture)*
- `items/modifiers/tools/build_master_mod_list.py` — broken; reads the removed `item_mods_src/types.py`. *(broken)*
- `items/modifiers/tools/game-mod-table-named-full.tsv` — TSV duplicate that drops the codes column of `../items/modifiers/tools/game-mod-table-named.txt`. *(duplicate)*
- `items/modifiers/tools/game_mod_table.py` — auto-generated 390-entry unlock table. *(generated)*
- `items/modifiers/tools/game_mod_tables.py` — auto-generated label/caps data. *(generated)*

## Loot

- `loot/redesign/` (7 files) — the superseded loot-redesign design batch: an
  implementation built from it was reverted. `how-it-works-today.md` remains a
  useful line-cited audit of the existing system; the folder's own
  `README.md` says what to read and what to ignore. *(superseded)*

## Maintenance

- `maintenance/records/README.md` — map of a records area that never held records; the migration manifest it named was intentionally discarded. *(placeholder)*

## Persistence

- `persistence/audit/audit-and-plan.md` — the original storage-boundary audit and plan, now executed; rules live in `../persistence/audit/migration-spec.md` and `migration-complete.md`. *(completed)*
- `persistence/ini-manager/` (7 files) — the completed `IniManager`/`IniHandler`/`configparser` → `Settings` migration: behavior guide for the removed API, requirement handover, and the removal execution records. Some record completion while leaving native rebuild or live-client verification open. *(completed)*

## UI / ImGui

- `ui/imgui/im-gui-facade-migration-plan.md` — design spec for the `ImGuiRuntime` facade; the rebuild was abandoned and deleted. *(abandoned)*
- `ui/imgui/im-gui-implementation-correction-instructions.md` — corrective handoff coupled to the abandoned facade. *(abandoned)*
- `ui/imgui/im-gui-layer2-ergonomics-proposal.md` — parked exploratory proposal; no code written. *(abandoned)*
- `ui/imgui/im-gui-legacy-functionality-categorization.md` — deprecation planning for a `ImGui_Legacy` retirement that never happened. *(abandoned)*

## UI / launch-bar and launch-surface

- `ui/launch-bar/launch-bar-im-gui-implementation-plan.md` — the locked interaction model as planned; the `launch_bar` package shipped and current source outranks it. *(completed)*
- `ui/launch-surface/` (6 files) — the removed `LaunchSurface` framework: design, feature/quality audits, user manual, component and provider guides. Replaced by `launch_bar`; its model/host/manager split informed the successor. *(superseded)*

## UI / map-overlay

- `ui/map-overlay/analysis.md`, `feature-inventory.md`, `package-shape.md` — design-phase records for the map-overlay merge; the merge shipped (`../ui/map-overlay/build-status.md`). *(superseded)*

## UI / name-tag colors

- `ui/name-tag-colors/feature-guide.md` — the earlier `PyAgentTagColor` API guide; current surface is `AgentRecolor`/`PyAgentRecolor`. *(superseded)*
- `ui/name-tag-colors/reverse-engineering.md` — resolver/detour evidence for that earlier surface. *(superseded)*

## UI / research

- `ui/research/native-gw-window-creation-investigation.md` — investigation trail, superseded by `../ui/research/window-creation-architecture.md`. *(superseded)*
- `ui/research/native-ui-title-and-encoded-string-reference.md` — session handover; the work was consolidated into `py_ui.h` and the canonical API. *(superseded)*
- `ui/research/title-rendering-research.md` — the 11-approach investigation; the outcome became `create_container_window_with_title`. *(superseded)*
- `ui/research/ui-controls-catalog.md` — carries its own correction banners; superseded by `ui-controls-master-catalog.md` and the creation recipes. *(superseded)*
- `ui/research/window-creation-architecture-backup.md` — empty cataloger placeholder. *(placeholder)*
- `ui/research/tools/find_find_related_frame.py` — Ghidra scratch script; the answer is recorded in `../ui/research/ui-frame-system-mapping.md`. *(stale tool)*
- `ui/research/probes/tools/` (39 scripts) — exploratory in-game probe scripts; their findings are consolidated in `window-creation-architecture.md`, `ui-elements-creation-recipes.md`, and `native-button-pipeline.md`. *(superseded)*
- `ui/research/probes/generated/` (5 captures) — transient test logs, an injection log, and an `imgui.ini` layout capture. *(capture)*

## Validation / demo

- `validation/demo/` (10 files) — pre-build analysis and the completed build plan for the demo replacement (44 sections shipped): v1/v2 inventories, coverage matrix, backend and binding inventories, harvest list, gaps, and transitional fix notes. *(completed)*

---

## Where the live knowledge lives

- Current sources, stubs, and topic maps remain authoritative: see `../README.md`
  and `../documentation-index.md`.
- Specific live counterparts: `../ui/launch-bar/`, `../ui/map-overlay/build-status.md`,
  `../ui/research/`, `../items/modifiers/item-mods-api.md` + `item-mods-design.md`,
  `../persistence/audit/`, `../loot/redesign/`, `../bridge/shared-memory/multibox-shmem-cpp-writer-postmortem.md`.
- If a file here is judged permanently useless, it can be deleted outright:
  everything is already preserved in Git history.
