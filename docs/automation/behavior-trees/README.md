# Behavior-Tree Documentation Map

This folder contains behavior-tree authoring, runtime, and metadata-discovery
guidance. It is separate from gameplay-specific bot records and from the
agent-workflow research documents.

## Authority and status

- `bottingtree-and-bt-routines-guide.md` describes the current relationship
  between `BehaviorTree`, `RoutinesBT`, `BottingTree`, and `ApoSource` wrappers.
- `behavior-tree-metadata-preparation-guide.md` records the metadata contract
  prepared for discovery/configurator tooling without redesigning runtime
  execution.
- `bot-factory-session-design.md` records the bot-authoring/configurator
  session that builds on the behavior-tree runtime and metadata work; it is a
  design/session record, not a replacement runtime implementation.
- Current source under `Py4GWCoreLib/`, `Sources/`, and active scripts outranks
  examples or historical parity references in the guides.
- The `C:\Users\Apo\Py4GW_python_files` paths in the BottingTree guide are
  legacy parity references, not current source paths.

## Related implementation

- `Py4GWCoreLib/py4gwcorelib_src/BehaviorTree.py` — core node/state/runtime
  semantics.
- `Py4GWCoreLib/routines_src/BehaviourTrees.py` — reusable routine trees.
- `Py4GWCoreLib/BottingTree.py` and `Py4GWCoreLib/botting_tree_src/` —
  orchestration and script-facing control.
- `Sources/ApoSource/` — local wrapper/authoring layer when used by a script.

## Review order

1. Read the runtime guide for ownership and lifecycle.
2. Read the metadata guide for discovery conventions.
3. Inspect the owning source and current script call sites.
4. Verify behavior with focused tree/runtime checks before changing semantics.
