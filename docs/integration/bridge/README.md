# Bridge and MCP Documentation Map

This folder contains the architecture note for exposing Py4GW capabilities to
external operators and MCP clients. It is separate from the shared-memory
implementation records and from `BridgeRuntime/`, which contains operator/runtime
usage material outside `docs/`.

## Authority and status

- `MCP_bridge.md` is the MCP-facing architecture and planning note, not the
  complete conceptual architecture source.
- `docs/architecture/conceptual_model/Py4GW_Conceptual_Model.md` remains the conceptual source of truth.
- `BridgeRuntime/README.md` documents daemon, injected client, CLI, and
  protocol operation.
- `py4gw_mcp_server.py`, `bridge_daemon.py`, and `bridge_cli.py` are current
  implementation entry points; inspect them before treating the note's
  "missing" list as current.
- The adapter intentionally exposes a narrow safe tool set. Do not infer that
  arbitrary reflective or mutating bridge calls are supported.

## Related integration records

- `../shared_memory/README.md` — Python/C++ shared-memory writer migration and
  layout invariants.
- `../../Py4GWCoreLib/GlobalCache/SharedMemory.py` — shared-memory consumer
  implementation.
- `../../Widgets/Coding/Tools/Bridge Client.py` — injected bridge client.

## Review order

1. Read the conceptual model for layer ownership.
2. Read `MCP_bridge.md` for bridge namespace and exposure assumptions.
3. Inspect the daemon, CLI, MCP adapter, and injected client for current
   behavior.
4. Consult `BridgeRuntime/README.md` for operator/runtime procedures.
