# FrameTree Documentation

This folder contains the FrameTree design and migration record. It is separate
from the reverse-engineering catalog because the design describes the Python
ownership model while `docs/game-client/research/` records native/UI evidence.

## Authority and status

- `frame-tree-design.md` records the agreed handle, registry, snapshot, failure,
  and migration decisions. Its original "not yet implemented" status was stale:
  `Py4GWCoreLib/FrameTree/` is present in the current tree. Treat the source
  package as authoritative for current behavior and this document as design and
  migration context.
- Verification and runtime claims must be checked against the current Python
  implementation, type diagnostics, and injected-client evidence. The design's
  deferred verification notes are not proof that verification has happened.

## Related evidence

- `docs/ui/research/ui-frame-system-mapping.md` — native frame-system mapping across
  WASM, EXE, and historical GWCA layers.
- `docs/ui/research/native-ui-controls-handover.md` — current native control creation
  findings and known limitations.
- `docs/archive/ui/research/native-gw-window-creation-investigation.md` — native window/container
  creation evidence.
- `docs/ui/research/ui-controls-master-catalog.md` — decompiler-verified control and
  message-dispatch catalog.
- `docs/ui/research/probes/tools/runtime_frame_tree_engine.py` — experimental/query-engine source
  referenced by the design; do not treat it as the active `FrameTree` package.

## Review order

1. Read the design for intended ownership and registry shape.
2. Inspect `Py4GWCoreLib/FrameTree/` for current implementation and API shape.
3. Consult the relevant `docs/game-client/research/` evidence before changing native frame or
   control assumptions.
4. Run focused Python/type/runtime checks appropriate to the change.
