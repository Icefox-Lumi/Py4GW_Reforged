# Shared-Memory Documentation Map

This folder contains the multi-account shared-memory writer migration and its
failure record. It is an integration boundary between Python shared-memory
consumers and the Reforged Native C++ writer.

## Authority and status

- `multibox_shmem_cpp_writer_plan.md` defines the locked migration scope and
  the byte/layout and ownership invariants.
- `multibox_shmem_cpp_writer_POSTMORTEM.md` records the resolved layout bug,
  root cause, and corrective evidence. Read it before changing the layout.
- Both documents report the migration as implemented and working; verify live
  behavior and the current native/Python sources before extending it.
- Coordination regions such as `Inbox`, `Intents`, and `HeroAIOptions` remain
  Python-written according to the migration record; do not infer that the C++
  writer owns them.

## Related implementation

- Python shared-memory readers and structures are under
  `Py4GWCoreLib/GlobalCache/` and its `shared_memory_src/` support modules.
- Native writer ownership is in the Reforged Native sibling project under its
  multibox module; inspect that source for ABI and layout changes.
- `docs/integration/bridge/MCP_bridge.md` covers bridge/MCP integration, not the byte-level shared
  memory migration itself.

## Review order

1. Read the plan and postmortem together.
2. Compare Python structures with the native mirror and verify `sizeof`/layout
   invariants.
3. Check map-load zeroing, account identity, slot liveness, and coordination
   ownership.
4. Run focused shared-memory/runtime checks before claiming integration success.
