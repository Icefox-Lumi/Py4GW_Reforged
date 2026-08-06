# Native UI Reverse-Engineering Probes

This folder holds exploratory native UI scripts, captured logs, and test
harnesses. Read `../README.md` first, then the relevant native UI handover or
control-pipeline reference before running a probe.

- `*_test.py`, `*_probe.py`, and harness files are exploratory runtime tools.
- `*_log.txt`, `*_results.txt`, and the injection log are captured evidence.
- `native_window.py` and `runtime_frame_tree_engine.py` are experiment support
  code, not general Py4GW runtime modules.

These artifacts are not a test suite. Preserve their historical context and
validate any conclusion against the current Reforged Native implementation and
a live injected client.
