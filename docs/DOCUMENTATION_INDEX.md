# Py4GW Documentation Index

Status: provisional inventory after reviewed organization batches. Index files
and generated `__pycache__` artifacts are excluded from their own inventory.
Paths shown are current and should be updated after each reviewed move.

## Use

- Start with the category and title tables below; open the source file before treating a statement as current truth.
- `provisional` means the category is inferred from the existing path/name and still requires topic/authority review.
- Do not treat similarly named plans, handovers, audits, postmortems, or backups as interchangeable; compare scope, date, and status inside the documents.

## Proposed taxonomy

| Category | Purpose | Current count |
|---|---|---:|
| `agent-workflow` | Agent instructions, skills, harness research, and prompt/workflow design. | 22 |
| `architecture-and-migration` | Demo replacement and cross-layer migration analysis. | 15 |
| `architecture-and-project-records` | Architecture models, design records, audits, pending work, and project-level decisions. | 10 |
| `automation-and-gameplay` | HeroAI, behavior trees, bot/build systems, and gameplay automation. | 19 |
| `gameplay-data` | Loot, item modifiers, catalogs, and gameplay data research. | 50 |
| `integration-and-bridge` | MCP, bridge, shared-memory, and external operator integration. | 6 |
| `migration` | Reforged migration records and parity/severance analysis. | 3 |
| `needs-review` | Root-level files not safely classified from path/name alone. | 0 |
| `persistence-and-storage` | Settings, INI, database, and persistence migration/behavior. | 14 |
| `reverse-engineering` | RE methodology, native catalogs, mappings, packets, UI internals, and probes. | 82 |
| `ui-and-rendering` | PyImGui, LaunchSurface, LaunchBar, overlay, frame-tree, and UI implementation/design. | 27 |


## Reviewed batch: persistence/ini_manager

- Seven INI/Settings documents were grouped without merging or rewriting them.
- `persistence/ini_manager/README.md` records current implementation evidence, authority, status, and contradictions.
- The documents remain historical or operational records until source/native/runtime evidence resolves their claims.

## Reviewed batch: ui/frame_tree

- `FrameTree_Design.md` was grouped with the UI/frame-tree topic without
  rewriting its design decisions.
- Its original "not yet implemented" status was flagged as stale because the
  current tree contains `Py4GWCoreLib/FrameTree/`.
- `ui/frame_tree/README.md` records the source-vs-design authority rule and
  links the related reverse-engineering evidence under `RE/`.

## Reviewed batch: ui/imgui/FloatingIcon

- `FloatingIcon_Class.md` was grouped with the active ImGui helper documents.
- The guide's historical `ImGui_Legacy` and `IniManager` wording is retained
  for context but flagged against the current `ImGui.FloatingIcon` source and
  `Settings` persistence implementation.

## Reviewed batch: ui/launch_bar

- `LaunchBar_ImGui_Implementation_Plan.md` was grouped separately from the
  predecessor LaunchSurface documents; the two systems are related but not
  interchangeable.
- The plan's original "not yet implemented" status was flagged as stale because
  `Py4GWCoreLib/py4gwcorelib_src/launch_bar/` is active and hosted by
  `Py4GW_widget_manager.py`.
- `ui/launch_bar/README.md` records the source-vs-plan authority rule and the
  review order.

## Reviewed batch: ui/overlay

- `overlay_3d_performance_issues.md` was grouped as a UI/native overlay
  troubleshooting record, separate from general ImGui and LaunchBar design.
- Its fixed causes, affected call sites, and unresolved `PF-5` issue remain
  evidence records; current source and injected-client measurements determine
  present behavior.
- `ui/overlay/README.md` records the relationship to the project-level
  `pending_fixes.md` list.

## Reviewed batch: persistence/database

- `database_manager_and_database_namespace.md` was grouped with database
  persistence without merging it into the INI/Settings records.
- Its source links now point to the current `Py4GWCoreLib` implementation; the
  older `DBMGR_HANDOVER.md` remains explicitly historical.
- `persistence/database/README.md` records the authority boundary and review order.

## Reviewed batch: integration/shared_memory

- The C++ writer migration plan and its postmortem were grouped together as one
  implementation record; neither was merged or rewritten.
- The postmortem remains the failure/root-cause record, while the plan preserves
  the locked layout, ownership, and coordination-region invariants.
- `integration/shared_memory/README.md` distinguishes this byte-level
  migration from the separate MCP/bridge transport layer.

## Reviewed batch: integration/bridge

- `MCP_bridge.md` was grouped with bridge/MCP architecture notes and kept
  separate from shared-memory layout records.
- Its conceptual-model link was corrected to the current relative location;
  `BridgeRuntime/README.md` remains the operator/runtime reference.
- `integration/bridge/README.md` records the transport/source-of-truth boundary
  and review order.

## Reviewed batch: agent_workflow/research

- The skills compendium, OpenCode capability research, and workflow redesign
  proposal were grouped by topic without treating them as one authority.
- The README distinguishes standards/ecosystem research, time-sensitive
  platform observations, and unapproved design proposals.

## Reviewed batch: automation/behavior_trees

- The metadata-preparation guide and BottingTree/Routines guide were grouped as
  one behavior-tree topic without merging their distinct purposes.
- Current `Py4GWCoreLib` sources outrank legacy parity-script references; broken
  relative links were corrected or made explicit as legacy paths.
- `automation/behavior_trees/README.md` records the runtime/metadata authority
  and review order.

## Reviewed batch: automation/heroai

- HeroAI combat, interrupt-feasibility, and UI-inventory records were grouped
  by subsystem without flattening their distinct evidence and status claims.
- `automation/heroai/README.md` records the source authority and the rule that
  UI inventory does not replace the owning UI documentation.

## Reviewed batch: automation/builds

- Build authoring, prompting, and `BuildMgr`/`SkillsTemplate` contract documents
  were grouped without merging workflow guidance into runtime contracts.
- `automation/builds/README.md` records current-source authority and review order.

## Reviewed batch: RE/name_tag_color

- The usage guide and reverse-engineering record were grouped under one topic
  without merging their distinct historical and implementation claims.
- The records describe the older `PyAgentTagColor` surface; current source,
  stubs, and tests use the expanded `PyAgentRecolor` module. The local README
  records this status gap and the current paths.

## Reviewed batch: architecture/conceptual_model and architecture/governance

- The canonical conceptual model is isolated under
  `architecture/conceptual_model/`.
- Traceability and migration review procedure is isolated under
  `architecture/governance/`; it is guidance for change review, not a runtime
  implementation contract.

## Reviewed batch: architecture/project_records

- `pending_fixes.md` and the cross-hero coordination whiteboard were grouped
  as project-level records without merging their separate issue and design
  semantics.
- References to the pending-fix identifiers were updated to the new canonical
  path; source and runtime evidence still outrank these records.

## Reviewed batch: automation/behavior_trees and automation/heroai

- The bot-factory session record was grouped with behavior-tree authoring and
  metadata documents without presenting it as a runtime implementation.
- The follower unstuck record was grouped with HeroAI subsystem records and
  remains distinct from combat, interrupt, and UI inventories.

## Reviewed batch: automation/hex_removal and ui/widget_manager

- The hex-removal architecture record is isolated from generic behavior-tree
  and HeroAI documentation while retaining its implementation dependencies.
- The widget manager/catalog guide is isolated as a UI/runtime ownership
  reference, distinct from LaunchBar and LaunchSurface presentation records.

## Reviewed batch: architecture/conceptual_model derivative

- `Py4GW_Model_Features_Detail.txt` now sits beside the canonical conceptual
  model and is explicitly marked as a derived quick-scan export.

## Reviewed batch: automation/builds category reconciliation

- `buildmgr_and_skills_template.md` is classified as
  `automation-and-gameplay` because its folder README and contents define a
  `BuildMgr`/`SkillsTemplate` runtime contract, not an unresolved root record.

## Reviewed batch: taxonomy parent maps

- Added navigation READMEs to the architecture, automation, integration,
  persistence, UI, and agent-workflow parent folders.
- These maps describe scope and authority without duplicating child documents;
  the JSON index remains the machine-readable inventory.

## Inventory

| Current path | Title | Category | Size |
|---|---|---|---:|
| `agent_workflow/README.md` | # Agent-Workflow Documentation | `agent-workflow` | 466 B |
| `agent_workflow/research/agent_skills_research.md` | # Agent Skills & Agentic Flows â€” Research Compendium | `agent-workflow` | 25734 B |
| `agent_workflow/research/opencode_agentic_workflow_research_2026-07.md` | # OpenCode Agentic Workflow Research | `agent-workflow` | 17351 B |
| `agent_workflow/research/opencode_workflow_redesign_proposal_2026-07.md` | # OpenCode Workflow Redesign Proposal | `agent-workflow` | 15033 B |
| `agent_workflow/research/README.md` | # Agent-Workflow Research Map | `agent-workflow` | 1299 B |
| `agents_md_replacement/AGENTS.md` | # Py4GW AGENTS.md - Draft | `agent-workflow` | 8812 B |
| `agents_md_replacement/AGENTS_merged_sources.md` | # AGENTS.md - Merged Source Draft | `agent-workflow` | 17980 B |
| `agents_md_replacement/AGENTS_py4gw.md` | # Py4GW AGENTS.md - Draft | `agent-workflow` | 25337 B |
| `agents_md_replacement/current_rule_source_scope.md` | # Current Py4GW Rule-Source Scope Map | `agent-workflow` | 8097 B |
| `agents_md_replacement/DESIGN_INTENT.md` | # Replacement Instruction System - Design Intent | `agent-workflow` | 2213 B |
| `agents_md_replacement/feature_inventory.md` | # AI Harness Feature Inventory for Py4GW | `agent-workflow` | 27335 B |
| `agents_md_replacement/project_specific_context_recovered.md` | # Recovered Py4GW Project-Specific Context | `agent-workflow` | 20727 B |
| `agents_md_replacement/py4gw_project_context.md` | # Py4GW Project Context | `agent-workflow` | 16985 B |
| `agents_md_replacement/README.md` | # AGENTS.md Replacement Working Set | `agent-workflow` | 362 B |
| `agents_md_replacement/SOURCES.md` | # Source Files | `agent-workflow` | 1467 B |
| `agents_md_replacement/sources/source_codex_AGENTS.md` | # Rust/codex-rs | `agent-workflow` | 22519 B |
| `agents_md_replacement/sources/source_codex_default.md` | You are a coding agent running in the Codex CLI, a terminal-based coding assistant. Codex CLI is an open source project led by OpenAI. You are expected to be precise, safe, and helpful. | `agent-workflow` | 20903 B |
| `agents_md_replacement/sources/source_opencode_anthropic.txt` | You are OpenCode, the best coding agent on the planet. | `agent-workflow` | 8212 B |
| `agents_md_replacement/sources/source_opencode_codex.txt` | You are OpenCode, the best coding agent on the planet. | `agent-workflow` | 7390 B |
| `architecture/conceptual_model/Py4GW_Conceptual_Model.md` | # Py4GW Conceptual Model | `architecture-and-project-records` | 85502 B |
| `architecture/conceptual_model/Py4GW_Model_Features_Detail.txt` | Py4GW Conceptual Model - Detailed Feature Summary | `architecture-and-project-records` | 10529 B |
| `architecture/conceptual_model/README.md` | # Conceptual Architecture Documentation | `architecture-and-project-records` | 570 B |
| `architecture/governance/pr_review_traceability_and_migration_analysis.md` | # PR Review Guide: Traceable Refactors and Migration Analysis | `architecture-and-project-records` | 39291 B |
| `architecture/governance/README.md` | # Architecture Governance Documentation | `architecture-and-project-records` | 458 B |
| `architecture/project_records/pending_fixes.md` | # Pending fixes â€” a pool of known issues, deliberately not fixed yet | `architecture-and-project-records` | 24969 B |
| `architecture/project_records/README.md` | # Architecture Project Records | `architecture-and-project-records` | 635 B |
| `architecture/project_records/whiteboard_architecture_cross-hero_cast_coordination.md` | # Whiteboard Architecture - Cross-Hero Locks | `architecture-and-project-records` | 14706 B |
| `architecture/README.md` | # Architecture Documentation | `architecture-and-project-records` | 407 B |
| `automation/behavior_trees/behavior_tree_metadata_preparation_guide.md` | # BehaviorTree Metadata Preparation Guide | `automation-and-gameplay` | 8155 B |
| `automation/behavior_trees/bot_factory_session_design.md` | # Bot Factory Session Design | `automation-and-gameplay` | 39024 B |
| `automation/behavior_trees/bottingtree_and_bt_routines_guide.md` | # BottingTree And BT Routines Guide | `automation-and-gameplay` | 32417 B |
| `automation/behavior_trees/README.md` | # Behavior-Tree Documentation Map | `automation-and-gameplay` | 1711 B |
| `automation/builds/build_authoring_handover.md` | # Build Authoring Handover | `automation-and-gameplay` | 8102 B |
| `automation/builds/build_prompting_guide.md` | # Build Prompting Guide | `automation-and-gameplay` | 7364 B |
| `automation/builds/buildmgr_and_skills_template.md` | # BuildMgr And SkillsTemplate | `automation-and-gameplay` | 10407 B |
| `automation/builds/README.md` | # Build-Authoring Documentation Map | `automation-and-gameplay` | 1054 B |
| `automation/heroai/Follower_resolves_unstuck.md` | # Per-Follower Smart Unstuck | `automation-and-gameplay` | 33700 B |
| `automation/heroai/heroai_combat_handover.md` | # HeroAI Combat Handover | `automation-and-gameplay` | 5954 B |
| `automation/heroai/HeroAi_interrupt_feasibility.md` | # HeroAi Interrupt Feasibility | `automation-and-gameplay` | 11370 B |
| `automation/heroai/HeroAI_UI_inventory.md` | # HeroAI UI Inventory | `automation-and-gameplay` | 10638 B |
| `automation/heroai/README.md` | # HeroAI Documentation Map | `automation-and-gameplay` | 1484 B |
| `automation/hex_removal/hex_removal_architecture_and_authoring.md` | # Hex Removal Architecture And Authoring | `automation-and-gameplay` | 23364 B |
| `automation/hex_removal/README.md` | # Hex-Removal Automation Documentation | `automation-and-gameplay` | 527 B |
| `automation/README.md` | # Automation Documentation | `automation-and-gameplay` | 492 B |
| `demo_replacement/01_demo_v1_legacy.md` | # DEMO v1 â€” Legacy `Py4GW_DEMO.py` | `architecture-and-migration` | 7543 B |
| `demo_replacement/02_demo_v2_modular.md` | # DEMO v2.0 â€” Modular `Py4GW DEMO 2.0.py` | `automation-and-gameplay` | 7173 B |
| `demo_replacement/03_coverage_matrix.md` | # Coverage Matrix â€” v1 vs v2 vs Backend | `architecture-and-migration` | 4887 B |
| `demo_replacement/04_backend_surface.md` | # Backend Surface Inventory | `architecture-and-migration` | 6880 B |
| `demo_replacement/05_gaps_and_considerations.md` | # Gaps & Considerations for the Replacement | `architecture-and-migration` | 4886 B |
| `demo_replacement/06_cpp_bindings_gameplay.md` | # C++ Bindings â€” GW Gameplay Domain | `architecture-and-migration` | 45068 B |
| `demo_replacement/07_cpp_bindings_infra_io.md` | # C++ Bindings â€” Infra / IO / Rendering | `architecture-and-migration` | 34390 B |
| `demo_replacement/08_contexts.md` | # Context Path â€” Native Structs & ctypes Readers | `architecture-and-migration` | 28937 B |
| `demo_replacement/09_python_reusable_scripts.md` | # Reusable Python Scripts (harvest candidates) | `architecture-and-migration` | 27815 B |
| `demo_replacement/10_python_wrapper_api.md` | # Python Wrapper API Surface (per-domain getters & actions) | `architecture-and-migration` | 56827 B |
| `demo_replacement/11_build_plan.md` | # DEMO 2.0 Build Plan â€” Every Module â†’ A View | `automation-and-gameplay` | 16367 B |
| `demo_replacement/DEBUG_STRUCTURE.md` | # Debug Structure & Workflow (DEMO 2.0 migration bug-fixing) | `architecture-and-migration` | 7464 B |
| `demo_replacement/README.md` | # Demo Replacement â€” Context & Analysis | `architecture-and-migration` | 3964 B |
| `demo_replacement/reengineer/R1_original_demo_patterns.md` | # R1 â€” Original Demo Patterns (gold-standard call + cast + render recipes) | `architecture-and-migration` | 27125 B |
| `demo_replacement/reengineer/R2_binding_method_inventory.md` | # R2 â€” Authoritative Binding Method Inventory | `architecture-and-migration` | 271486 B |
| `demo_replacement/reengineer/R3_wrapper_casting.md` | # R3 â€” Wrapper Casting Recipes (raw return â†’ proper cast â†’ readable fields) | `architecture-and-migration` | 28733 B |
| `demo_replacement/reengineer/R4_current_shortcut_audit.md` | # R4 â€” Current DEMO 2.0 Shortcut Audit | `architecture-and-project-records` | 13575 B |
| `demo_replacement/reengineer/SPEC_reengineer.md` | # DEMO 2.0 â€” Reengineer Spec (APPROVAL GATE) | `architecture-and-migration` | 17244 B |
| `integration/bridge/MCP_bridge.md` | # Py4GW MCP Bridge Notes | `integration-and-bridge` | 16268 B |
| `integration/bridge/README.md` | # Bridge and MCP Documentation Map | `integration-and-bridge` | 1566 B |
| `integration/README.md` | # Integration Documentation | `integration-and-bridge` | 391 B |
| `integration/shared_memory/multibox_shmem_cpp_writer_plan.md` | # Multi-account Shared Memory â€” move the writer to C++ | `integration-and-bridge` | 8363 B |
| `integration/shared_memory/multibox_shmem_cpp_writer_POSTMORTEM.md` | # Multibox Shared Memory -> C++ Writer Migration: Incident & Resolution | `integration-and-bridge` | 5561 B |
| `integration/shared_memory/README.md` | # Shared-Memory Documentation Map | `integration-and-bridge` | 1614 B |
| `item_mods/01_raw_modifier_layer.md` | # 01 â€” The Raw Modifier Layer (C++ backend + PyItem binding) | `gameplay-data` | 7751 B |
| `item_mods/02_encoded_strings.md` | # 02 â€” Encoded Strings (decode engine + byte builder) | `gameplay-data` | 5914 B |
| `item_mods/03_current_python_system.md` | # 03 â€” The Current Python System (`Py4GWCoreLib/item_mods_src/`) | `gameplay-data` | 11015 B |
| `item_mods/04_frenkeylib_reference.md` | # 04 â€” frenkeyLib Reference (`LootEx` + `mods_parser`) | `gameplay-data` | 8753 B |
| `item_mods/05_comparison_and_painpoints.md` | # 05 â€” Comparison & Pain Points | `gameplay-data` | 7127 B |
| `item_mods/06_game_mod_engine_RE.md` | # 06 â€” The Game's Mod Engine (Reverse-Engineering Findings) | `gameplay-data` | 9134 B |
| `item_mods/07_game_mod_table.md` | # 07 â€” The Game's Mod Table (extracted) | `gameplay-data` | 4580 B |
| `item_mods/08_native_name_binding.md` | # 08 â€” Native binding: name the mod table via the game's composer | `reverse-engineering` | 3269 B |
| `item_mods/09_item_catalogs.md` | # 09 â€” Item Catalogs (the whole universe) | `gameplay-data` | 4021 B |
| `item_mods/10_item_mods_api.md` | # 10 â€” `Item.Mods` API (the mod read/filter layer) | `gameplay-data` | 6161 B |
| `item_mods/11_mod_system_research.md` | # 11 â€” Item-Mod System: Research & Design (for approval) | `gameplay-data` | 14259 B |
| `item_mods/12_item_mods_design.md` | # 12 â€” `Item.Mods`: Agreed Design | `gameplay-data` | 20457 B |
| `item_mods/catalogs/attributes.csv` | index,text_id,text | `gameplay-data` | 10212 B |
| `item_mods/catalogs/books.csv` | index,f00,f04,f08,f0c,f10,f14,f18 | `gameplay-data` | 1531 B |
| `item_mods/catalogs/colors.csv` | index,text_id,text | `gameplay-data` | 240 B |
| `item_mods/catalogs/descriptions.csv` | index,text_id,text | `gameplay-data` | 41554 B |
| `item_mods/catalogs/elements.csv` | index,name_id,material,f04,f08 | `gameplay-data` | 1559 B |
| `item_mods/catalogs/formulas.csv` | index,price,ingredient_count,ingredients | `gameplay-data` | 80069 B |
| `item_mods/catalogs/formulas_recipes.json` | { | `gameplay-data` | 164599 B |
| `item_mods/catalogs/mod_identifiers.csv` | modid,value_arg,n_mods,example_names,example_descriptions | `gameplay-data` | 9869 B |
| `item_mods/catalogs/mod_master_list.csv` | upgrade_id,name,source,codes | `gameplay-data` | 27504 B |
| `item_mods/catalogs/mod_naming_audit.txt` | MOD NAMING AUDIT | `gameplay-data` | 166328 B |
| `item_mods/catalogs/mod_parity_scan.txt` | MOD PARITY SCAN  (GAME enc-strings vs. Item.Mods decode) | `gameplay-data` | 159027 B |
| `item_mods/catalogs/pvp_items.csv` | index,model_id,name_id,base_name,type_mask | `gameplay-data` | 16476 B |
| `item_mods/catalogs/pvp_unlocks.csv` | index,upgrade_id,name,description,codes | `gameplay-data` | 47567 B |
| `item_mods/catalogs/raw_item_catalogs.json` | { | `gameplay-data` | 191847 B |
| `item_mods/catalogs/single_item_dump.txt` | ============================================================ | `gameplay-data` | 745 B |
| `item_mods/mod_defs_sketch.py` | """ | `gameplay-data` | 7649 B |
| `item_mods/README.md` | # Item Mod System â€” Context & Reference | `gameplay-data` | 7890 B |
| `item_mods/tools/build_master_mod_list.py` | """ | `gameplay-data` | 3889 B |
| `item_mods/tools/dump_mod_tables_ghidra.py` | # Ghidra Jython dumper â€” GW item-mod tables | `reverse-engineering` | 4699 B |
| `item_mods/tools/format_catalogs.py` | """ | `gameplay-data` | 5399 B |
| `item_mods/tools/game_mod_table.py` | # AUTO-GENERATED from Gw.wasm ConstItemPvp unlock table (DAT@0x001b5990, 0x186 entries). | `gameplay-data` | 68446 B |
| `item_mods/tools/game_mod_table_named.txt` | GAME MOD TABLE â€” names composed by the game (native get_pvp_unlock_name_enc) | `gameplay-data` | 56066 B |
| `item_mods/tools/game_mod_table_named_full.tsv` | 0	0x0	<pending>	 | `gameplay-data` | 32159 B |
| `item_mods/tools/game_mod_tables.py` | # AUTO-GENERATED by docs/item_mods/tools/dump_mod_tables_ghidra.py | `gameplay-data` | 13289 B |
| `item_mods/tools/game_mod_tables_resolved.txt` | RESOLVED LABEL TABLES (ETextStr id -> in-game text) | `gameplay-data` | 48243 B |
| `llm_instructions/code-reviewer.md` | --- | `agent-workflow` | 9084 B |
| `llm_instructions/code-simplifier.md` | --- | `agent-workflow` | 1321 B |
| `llm_instructions/PYTHON_PATTERNS.md` | --- | `agent-workflow` | 17498 B |
| `loot_redesign/00_index.md` | # Loot redesign â€” document index | `gameplay-data` | 2022 B |
| `loot_redesign/01_class.md` | # The Loot Class â€” design | `gameplay-data` | 82596 B |
| `loot_redesign/02_implementation_spec.md` | # Implementation specification â€” the *how* | `gameplay-data` | 42859 B |
| `loot_redesign/legacy/00_index.md` | # Loot Config redesign â€” index | `gameplay-data` | 2697 B |
| `loot_redesign/legacy/01_loot_redesign.md` | # Loot Config â€” Redesign | `gameplay-data` | 33588 B |
| `loot_redesign/legacy/02_how_it_works_today.md` | # How looting works today â€” verified ground truth | `gameplay-data` | 20842 B |
| `loot_redesign/legacy/03_structure_and_build.md` | # Loot Config â€” Structure & Build Order | `gameplay-data` | 13227 B |
| `loot_redesign/legacy/dropinfo.json` | { | `gameplay-data` | 16046 B |
| `loot_redesign/legacy/grouping.json` | { | `gameplay-data` | 5052 B |
| `loot_redesign/legacy/grouping_review.json` | { | `gameplay-data` | 41379 B |
| `loot_redesign/legacy/README.md` | # LEGACY â€” superseded, not the basis for the new class | `gameplay-data` | 1586 B |
| `loot_redesign/legacy/reverted_audit_vs_plan.md` | # Audit â€” the REVERTED implementation vs. the plan | `gameplay-data` | 8372 B |
| `loot_redesign/legacy/reverted_implementation_log.md` | # Reverted implementation log â€” historical record only | `gameplay-data` | 11473 B |
| `loot_redesign/legacy/salvage_mapping.json` | { | `gameplay-data` | 144265 B |
| `loot_redesign/legacy/salvage_mapping_review.json` | { | `gameplay-data` | 254953 B |
| `map_overlay_merge/00_analysis.md` | # Map Overlay Merge â€” Analysis (Context Phase) | `ui-and-rendering` | 11980 B |
| `map_overlay_merge/01_feature_inventory.md` | # Map Overlay Merge â€” Feature Inventory (Union) | `ui-and-rendering` | 7609 B |
| `map_overlay_merge/02_package_shape.md` | # Map Overlay Merge â€” Package Shape (Design Phase) | `ui-and-rendering` | 6838 B |
| `map_overlay_merge/03_build_status.md` | # Map Overlay Merge â€” Build Status | `ui-and-rendering` | 4790 B |
| `migration_to_reforged/frenkeylib_severance_audit.md` | # frenkeyLib â€” Severance Audit | `persistence-and-storage` | 9441 B |
| `migration_to_reforged/session_01_complete.md` | # Migration to Reforged â€” Session Log | `persistence-and-storage` | 4709 B |
| `migration_to_reforged/session_01_intake.md` | # Migration to Reforged â€” Session Log | `migration` | 3111 B |
| `modular/architecture.md` | # Modular JSON BT Architecture | `automation-and-gameplay` | 2641 B |
| `persistence/database/database_manager_and_database_namespace.md` | # Database Manager And Database Namespace | `persistence-and-storage` | 4851 B |
| `persistence/database/README.md` | # Database Documentation Map | `persistence-and-storage` | 1173 B |
| `persistence/ini_manager/Configparser_To_Settings_Migration_Plan.md` | # Raw configparser â†’ Settings Migration Plan | `persistence-and-storage` | 12781 B |
| `persistence/ini_manager/ini_manager_behavior_and_usage_guide.md` | # IniManager Behavior And Usage Guide | `persistence-and-storage` | 14653 B |
| `persistence/ini_manager/IniHandler_Removal_Plan.md` | # IniHandler â†’ Settings Removal Plan | `persistence-and-storage` | 5908 B |
| `persistence/ini_manager/IniManager_Gut_To_Settings_Plan.md` | # IniManager â†’ Settings Migration Plan (authoritative) | `persistence-and-storage` | 15926 B |
| `persistence/ini_manager/IniManager_Migration_Handover.md` | # IniManager Migration â€” Handover (Requirement Only) | `persistence-and-storage` | 3208 B |
| `persistence/ini_manager/IniManager_Migration_Plan.md` | # IniManager â†’ Settings Migration Plan (LOCKED) | `persistence-and-storage` | 6447 B |
| `persistence/ini_manager/IniManager_Removal_Plan.md` | # IniManager Removal Plan (delete the shell, callers use Settings directly) | `persistence-and-storage` | 6150 B |
| `persistence/ini_manager/README.md` | # INI and Settings Documentation Map | `persistence-and-storage` | 3610 B |
| `persistence/README.md` | # Persistence Documentation | `persistence-and-storage` | 395 B |
| `persistence_jail/01_audit_and_plan.md` | # Persistence Path-Jail â€” Repo-Wide Audit & Plan | `persistence-and-storage` | 8649 B |
| `persistence_jail/02_migration_spec.md` | # Persistence Migration Spec â€” how to convert every file | `migration` | 5687 B |
| `persistence_jail/03_migration_complete.md` | # Persistence Path-Jail â€” Completion Report | `migration` | 5160 B |
| `RE/CPP_WASM_MAPPING.md` | # CPP â†” WASM â†” EXE Mapping Guide | `reverse-engineering` | 16399 B |
| `RE/CPP_WASM_MAPPING.md.bak` | placeholder - backup created via cataloger on 2026-06-05 | `reverse-engineering` | 56 B |
| `RE/find_find_related_frame.py` | """ | `reverse-engineering` | 2816 B |
| `RE/gw_combat_ai_reverse_engineering.md` | # Guild Wars Combat AI Reverse Engineering | `reverse-engineering` | 60640 B |
| `RE/handover.md.bak` | placeholder â€” handover.md backup created 2026-06-06 | `reverse-engineering` | 53 B |
| `RE/inventory_slot_tint_reverse_engineering.md` | # Native inventory-slot tinting | `reverse-engineering` | 20953 B |
| `RE/map_travel_research.md` | # Map Travel â€” Reverse Engineering Research | `reverse-engineering` | 25115 B |
| `RE/map_travel_reverse_engineering.md` | # Guild Wars Map Travel â€” Reverse Engineering (2026-06-08) | `reverse-engineering` | 63644 B |
| `RE/map_travel_reverse_engineering.md.bak` | # Guild Wars Map Travel â€” Reverse Engineering (2026-06-08) | `reverse-engineering` | 194 B |
| `RE/name_obfuscation_reverse_engineering.md` | # Name Obfuscation Reverse Engineering | `reverse-engineering` | 28827 B |
| `RE/name_tag_color/Feature_Guide.md` | # Agent Name-Tag Coloring (`PyAgentTagColor`) | `reverse-engineering` | 6478 B |
| `RE/name_tag_color/README.md` | # Name-Tag Color Documentation Map | `reverse-engineering` | 1174 B |
| `RE/name_tag_color/Reverse_Engineering.md` | # Agent / Item Name-Tag Color Reverse Engineering | `reverse-engineering` | 19403 B |
| `RE/native_button_pipeline.md` | # Native UI Controls â€” Complete Pipeline & Reference | `reverse-engineering` | 55366 B |
| `RE/native_dialog_layout_process.md` | # Native GW Dialog Construction & Layout â€” complete process (WASM-first RE) | `reverse-engineering` | 14144 B |
| `RE/native_gw_ui_function_catalog.json` | [ | `reverse-engineering` | 17762 B |
| `RE/native_gw_ui_function_catalog.json.bak` | placeholder - backup created via cataloger on 2026-06-05 | `reverse-engineering` | 56 B |
| `RE/native_gw_window_creation_investigation.md` | # Native GW Window Creation Investigation | `reverse-engineering` | 26705 B |
| `RE/native_ui_controls_handover.md` | # Native UI Controls â€” HANDOVER | `reverse-engineering` | 25233 B |
| `RE/native_ui_title_and_encoded_string_reference.md` | > **Backend note â€” we are on Reforged.** The current C++ backend is the **`Py4GW_Reforged_Native`** project (`../Py4GW_Reforged_Native`): migrated managers in `src\GW\<module>\` + `include\GW\<module>\`, addresses resolved from `offsets\<module>.json`. It **replaces legacy GWCA**. In this doc, GWCA names and `../Py4GW/vendor/gwca` paths are **legacy cross-references** (canonical nomenclature / pre-Reforged behavior), not the source of truth for current code â€” the live implementation is in `Py4GW_Reforged_Native`. `Gw.exe`/`Gw.wasm` addresses remain valid. | `reverse-engineering` | 34353 B |
| `RE/packet_sniffers_reference.md` | # Packet Sniffers Reference | `reverse-engineering` | 7465 B |
| `RE/player_skill_system_callable_functions.md` | # Player Skill System â€” Callable Functions Reference | `reverse-engineering` | 13487 B |
| `RE/quest_data_request_pipeline.md` | # Quest Data Request Pipeline | `reverse-engineering` | 10406 B |
| `RE/README.md` | # RE Documentation Index | `reverse-engineering` | 5553 B |
| `RE/reverse_engineering_reference.md` | # Reverse Engineering Reference | `reverse-engineering` | 107613 B |
| `RE/rosetta_stone.txt` | ================================================================================ | `reverse-engineering` | 42249 B |
| `RE/struct_identification_methodology.md` | # Struct Identification Methodology | `reverse-engineering` | 28579 B |
| `RE/title_rendering_research.md` | # Window Title Rendering â€” Investigation Summary (2026-06-02) | `reverse-engineering` | 7963 B |
| `RE/ui_controls_catalog.md` | # Guild Wars UI Controls Catalog | `reverse-engineering` | 24218 B |
| `RE/ui_controls_master_catalog.md` | # GW UI Controls - Master Catalog (Ghidra swarm, 2026-07-01) | `reverse-engineering` | 888181 B |
| `RE/ui_elements_creation_recipes.md` | # GW UI Elements â€” Corrected Creation Recipes (Ghidra-verified) | `reverse-engineering` | 100105 B |
| `RE/ui_frame_system_mapping.md` | # UI Frame System â€” GWCA â†” WASM â†” EXE Mapping | `reverse-engineering` | 36315 B |
| `RE/UI_RE/button_test.py` | """ | `reverse-engineering` | 7745 B |
| `RE/UI_RE/clone_devsound_window.py` | from Py4GWCoreLib import GWContext, PyImGui, Scanner, UIManager | `reverse-engineering` | 5795 B |
| `RE/UI_RE/clone_devtext_window.py` | from Py4GWCoreLib import GWContext, PyImGui, UIManager | `reverse-engineering` | 4686 B |
| `RE/UI_RE/container_window_poc.py` | """ | `reverse-engineering` | 4891 B |
| `RE/UI_RE/devtext_clone_text_component_test.py` | import ctypes | `reverse-engineering` | 10615 B |
| `RE/UI_RE/devtext_insert_text_frame_test.py` | import ctypes | `reverse-engineering` | 9528 B |
| `RE/UI_RE/devtext_resource_caption_test.py` | import ctypes | `reverse-engineering` | 15233 B |
| `RE/UI_RE/empty_window_native_element_test.py` | import time | `reverse-engineering` | 21290 B |
| `RE/UI_RE/empty_window_text_label_test.py` | import time | `reverse-engineering` | 6101 B |
| `RE/UI_RE/empty_window_title_override_test.py` | import ctypes | `reverse-engineering` | 13929 B |
| `RE/UI_RE/encoded_text_payload_dump.py` | import ctypes | `reverse-engineering` | 8245 B |
| `RE/UI_RE/flat_button_click_test.py` | """ | `reverse-engineering` | 45389 B |
| `RE/UI_RE/gwui_controls_test.py` | """ | `reverse-engineering` | 12186 B |
| `RE/UI_RE/helper_frame_callback_graft_test.py` | import time | `reverse-engineering` | 14979 B |
| `RE/UI_RE/hosted_frame_list_probe_test.py` | import ctypes | `reverse-engineering` | 16050 B |
| `RE/UI_RE/imgui.ini` | [Window][Debug##Default] | `reverse-engineering` | 1002 B |
| `RE/UI_RE/inspect_devtext_runtime_tree.py` | import time | `reverse-engineering` | 11439 B |
| `RE/UI_RE/inventory_component_clone_test.py` | import time | `reverse-engineering` | 10686 B |
| `RE/UI_RE/inventory_into_devtext_clone_test.py` | import time | `reverse-engineering` | 13233 B |
| `RE/UI_RE/inventory_into_devtext_test.py` | import time | `reverse-engineering` | 10991 B |
| `RE/UI_RE/inventory_into_empty_devtext_clone_test.py` | import time | `reverse-engineering` | 13360 B |
| `RE/UI_RE/native_button_test_harness.py` | """ | `reverse-engineering` | 29214 B |
| `RE/UI_RE/native_layout_log.txt` | [20:22:59] CREATING checkbox (page path) ... | `reverse-engineering` | 2469 B |
| `RE/UI_RE/native_layout_test.py` | """ | `reverse-engineering` | 7453 B |
| `RE/UI_RE/NATIVE_WINDOW.py` | """ | `reverse-engineering` | 3149 B |
| `RE/UI_RE/options_caption_resource_test.py` | import ctypes | `reverse-engineering` | 9259 B |
| `RE/UI_RE/original_devtext_caption_test.py` | import time | `reverse-engineering` | 3572 B |
| `RE/UI_RE/Py4GW_injection_log.txt` | 2026-05-30 16:26:25 [INFO] Terminating DLL... | `reverse-engineering` | 5405 B |
| `RE/UI_RE/RuntimeFrameTreeEngine.py` | from collections import defaultdict, deque | `reverse-engineering` | 50367 B |
| `RE/UI_RE/test_edittext_fix.py` | """ | `reverse-engineering` | 3811 B |
| `RE/UI_RE/test_slider_fix.py` | """ | `reverse-engineering` | 9031 B |
| `RE/UI_RE/test_tabs_fix.py` | """ | `reverse-engineering` | 4082 B |
| `RE/UI_RE/test_tier1_creates.py` | """ | `reverse-engineering` | 10152 B |
| `RE/UI_RE/test_tier1_ui.py` | """ | `reverse-engineering` | 12934 B |
| `RE/UI_RE/text_button_render_test.py` | """ | `reverse-engineering` | 5260 B |
| `RE/UI_RE/text_label_on_empty_clone_test.py` | import time | `reverse-engineering` | 14736 B |
| `RE/UI_RE/title_test.py` | """ | `reverse-engineering` | 1365 B |
| `RE/UI_RE/ui_elements_test.py` | """ | `reverse-engineering` | 7216 B |
| `RE/UI_RE/ui_test_log.txt` | [10:27:45] CREATING button ... | `reverse-engineering` | 3825 B |
| `RE/UI_RE/ui_test_results.txt` | GWUI native control test results | `reverse-engineering` | 635 B |
| `RE/UI_RE/verify_assertions.py` | """ | `reverse-engineering` | 1794 B |
| `RE/UI_RE/weaponbar_component_creation_test.py` | import time | `reverse-engineering` | 6846 B |
| `RE/UI_RE/window_caption_test.py` | import ctypes | `reverse-engineering` | 26810 B |
| `RE/UI_RE/window_contents_test.py` | """ | `reverse-engineering` | 7479 B |
| `RE/UI_RE/window_title_hook_probe_test.py` | import ctypes | `reverse-engineering` | 10911 B |
| `RE/UI_RE/window_title_probe_test.py` | import time | `reverse-engineering` | 7286 B |
| `RE/window_creation_architecture.md` | # Arbitrary Window Creation â€” WASM Architecture Analysis | `reverse-engineering` | 32162 B |
| `RE/window_creation_architecture.md.bak` | placeholder - backup created via cataloger on 2026-06-05 | `reverse-engineering` | 56 B |
| `ui/frame_tree/FrameTree_Design.md` | # FrameTree - design spec | `ui-and-rendering` | 20014 B |
| `ui/frame_tree/README.md` | # FrameTree Documentation | `ui-and-rendering` | 1792 B |
| `ui/imgui/FloatingIcon_Class.md` | # FloatingIcon Class | `ui-and-rendering` | 9462 B |
| `ui/imgui/HTML_Mockup_to_ImGui_Guide.md` | # HTML Mockup â†’ ImGui: Porting Guide | `ui-and-rendering` | 12292 B |
| `ui/imgui/ImGui_Facade_Migration_Plan.md` | # ImGui Facade Migration Plan | `ui-and-rendering` | 56190 B |
| `ui/imgui/ImGui_Implementation_Correction_Instructions.md` | # ImGui Implementation Correction Instructions | `ui-and-rendering` | 9898 B |
| `ui/imgui/ImGui_Layer2_Ergonomics_Proposal.md` | # ImGui Layer-2 Ergonomics Proposal (PARKED â€” resume later) | `ui-and-rendering` | 6989 B |
| `ui/imgui/ImGui_Legacy_Functionality_Categorization.md` | # ImGui_Legacy Functionality Categorization | `ui-and-rendering` | 16029 B |
| `ui/imgui/README.md` | # ImGui Documentation Map | `ui-and-rendering` | 1963 B |
| `ui/launch_bar/LaunchBar_ImGui_Implementation_Plan.md` | # Launch Bar â€” ImGui Implementation Plan | `ui-and-rendering` | 20295 B |
| `ui/launch_bar/README.md` | # LaunchBar Documentation Map | `ui-and-rendering` | 1740 B |
| `ui/launch_surface/LaunchSurface_Component_Guide.md` | # Launch Surface Component Guide | `ui-and-rendering` | 2660 B |
| `ui/launch_surface/LaunchSurface_Framework_Design.md` | # Launch Surface Framework Design | `ui-and-rendering` | 32769 B |
| `ui/launch_surface/LaunchSurface_Provider_Guide.md` | # Launch Surface Provider Guide | `ui-and-rendering` | 2780 B |
| `ui/launch_surface/LaunchSurface_Quality_Audit.md` | # Launch Surface Quality Audit | `ui-and-rendering` | 7617 B |
| `ui/launch_surface/LaunchSurface_UI_Feature_Audit.md` | # Launch Surface UI Feature Audit | `ui-and-rendering` | 20753 B |
| `ui/launch_surface/LaunchSurface_User_Manual.md` | # Launch Surface User Manual | `ui-and-rendering` | 5591 B |
| `ui/launch_surface/README.md` | # LaunchSurface Documentation Map | `ui-and-rendering` | 1539 B |
| `ui/overlay/overlay_3d_performance_issues.md` | # Overlay 3D drawing â€” performance issues | `ui-and-rendering` | 11817 B |
| `ui/overlay/README.md` | # Overlay Documentation Map | `ui-and-rendering` | 1271 B |
| `ui/README.md` | # UI and Rendering Documentation | `ui-and-rendering` | 549 B |
| `ui/widget_manager/README.md` | # Widget Manager Documentation | `ui-and-rendering` | 574 B |
| `ui/widget_manager/widget_manager_and_catalog.md` | # Widget Manager And Catalog | `ui-and-rendering` | 10889 B |

## Next review batches

1. Review `needs-review` root documents and assign each to an evidence-backed category.
2. Review one existing thematic directory at a time for duplicate, superseded, contradictory, and reinforcing documents.
3. Build authority/status metadata before moving files; update relative links after each batch.
4. Move only a reviewed batch and verify all references, scripts, and index entries afterward.
