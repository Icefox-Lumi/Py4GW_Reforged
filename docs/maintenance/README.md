# Documentation Maintenance

This directory owns documentation metadata and maintenance utilities. It does
not establish subsystem behavior or replace a topic's source and runtime
evidence.

Formatting, provenance, and move rules live in
`documentation-style-guide.md`.

- `generate_documentation_index.py` rebuilds `../documentation-index.md` and
  `../documentation-index.json` from the current tree.

Run from the repository root:

```text
python docs/maintenance/generate_documentation_index.py
```
