# Overlay Documentation Map

This folder contains UI-overlay troubleshooting and performance records. It is
separate from ImGui and LaunchBar because these documents concern the 3D/native
overlay resource and render-thread boundary.

## Authority and status

- `overlay-3d-performance-issues.md` is a troubleshooting/postmortem record,
  not a general overlay API reference. It records two fixed issues and one
  unresolved DXOverlay-vs-ImGui performance issue.
- Current Python/C++ source, native runtime evidence, and injected-client
  measurements outrank the historical narrative in the record.
- The unresolved `PF-5` item is tracked in
  `docs/architecture/records/pending-fixes.md`; keep the
  issue record and the project-wide pending-fix list cross-referenced rather
  than duplicating their ownership.

## Review order

1. Read the troubleshooting record for symptoms, root cause, affected call
   sites, and known fixes.
2. Inspect `Py4GWCoreLib/DXOverlay.py` and the owning native renderer before
   changing lifecycle or allocation behavior.
3. Consult `docs/architecture/records/pending-fixes.md` for the
   current status of `PF-5`.
4. Use injected-client timing and render evidence for claims that offline code
   inspection cannot prove.
