# Native UI Reverse-Engineering Probes

This folder holds the current in-client native UI harnesses. Read
`../README.md` first, then the relevant native UI handover or control-pipeline
reference before running a probe.

- `tools/gwui_controls_test.py` - in-client test harness for the GWUI toolkit;
  auto-saves verdicts to `generated/ui-test-results.txt` and events to
  `generated/ui-test-log.txt`.
- `tools/native_layout_test.py` - isolated harness for the native content-page
  path; crash-safe log at `generated/native-layout-log.txt`.

`generated/` receives the harnesses' crash-safe captures. These captures are
transient live evidence, not a committed authority; they regenerate on every
run and should not be treated as durable records.

The superseded exploratory probe scripts and earlier captured logs are
preserved under `../../archive/ui/research/probes/`.

These artifacts are not a test suite. Validate any conclusion against the
current Reforged Native implementation and a live injected client.
