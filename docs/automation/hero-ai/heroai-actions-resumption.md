# HeroAI Actions resumption handoff

Status: current; project paused, unfinished and not approved for deployment.
Scope: personal HeroAI Actions bounded Option A v3 and two temporary diagnostics.
Authority: owning source, preserved baseline/package hashes, prior offline test
results and independent review artifacts. No live formation proof is claimed.

## Checkpoint and preservation

- Branch: `Personal/HeroAI-Actions`.
- Parent HEAD: `e1f6d41d699c15bd12afb9a2f4213a522c510057`.
- Intended local commit title: `Park HeroAI Actions party formation work`.
- Checkpoint: the local commit containing this handoff. Its exact hash is
  recorded in the permanent parking folder's `checkpoint.json`; keeping that
  record outside the commit avoids a self-referential commit hash.
- Return branch: `Personal/Builds`, currently
  `cbc7241e1fd38cdcbfcab1791c5091255ff05b8f` (237 commits beyond this branch's base).
- Permanent parking destination, relative to the user's Desktop:
  `Py4GW-Recovery/HeroAI-Actions-Parked-20261026T044958Z-c808180c`.
- Permanent placement was verified before staging. The original archive
  preparation remains in EDITS at
  `.local-tests/heroai-parking/HeroAI-Actions-Parked-20261026T044958Z-c808180c`.
  The permanent folder is the resumption authority. The existing local exclude
  rule already covers `.local-tests`; no ignore rule was changed.
- No stashes or unrelated staged/unstaged EDITS changes were found at the start
  of parking. All 15 existing dirty files belonged to this project; the
  checkpoint adds this handoff and its nearest README entry.

The archive contains current project files, original EDITS/TESTS baselines,
tracked and proposed checkpoint diffs, Git/index/status evidence, historical
reports, independent review results, and hashes with original source paths.
Existing packages and installation receipts remain at their original locations.
No private runtime configuration, generated DLL, or live-client log is selected
for the checkpoint. This document and its nearest README are the only new
documentation changes. Exact inventory and completion state belong to the
parking folder's `manifest.json` and `checkpoint.json`.

## Intended behavior and boundaries

An explicit leader Form Party request may invite eligible solo alternates in
the exact same supported outpost instance. Each alternate must have persistent,
default-off authorization for that named leader. After one-time setup, the
alternate uses its existing HeroAI/Messaging components; Actions runs on the
leader. Travel remains a separate command.

Formation uses an operation-specific, versioned bounded protocol. It grants no
ordinary messaging permission, coordination claims, reservations, isolation
bypass or permanent grouping. V3 retains never-prepared cancellation evidence
until the matching receiver durably clears its safety marker and acknowledges
cleanup. Prepared or possibly dispatched attempts remain quarantined. Lost
evidence and previously stranded v2 markers have no automatic reset mechanism.

The full implementation includes necessary imports from the original TESTS
baseline into older EDITS shared owners. The large Messaging diff is not all
new formation code. `baseline-import.diff` and `formation-only.diff` preserve
that distinction. Do not transplant the combined checkpoint as a shared-library
upgrade without comparing these layers.

## Package and review state

Keep these paths unchanged under Desktop/Py4GW-Recovery:

- `HeroAI-OptionA-v2-20261026T012427Z-16922c48`
- `HeroAI-OptionA-v3-20261026T024827Z-d22b0d47`

V1 remains in the original temporary recovery directory named
`HeroAI-OptionA-Recovery-20261026T000454Z-41b056dc`; relevant original artifacts
are also copied into the parking archive. Do not move installation receipts.

V3 release manifest SHA-256:
`7cc15102c0741e07339048aaedaa58b26bb317f4e4f6093f975a2bf9fd01fbf0`.

Source/package review: **PASS within the reported offline scope**. The pause
request records this review status; available independent v3 artifacts support
scope preservation, matching compatibility outcomes, zero added static-check
occurrences, and exact-package deployment/rollback in an external fixture.
This is not runtime approval. V3's stored `independent_review` release gate and
all deployment/runtime approval flags remain false and were not edited.

Prior results, retained rather than rerun during parking:

- Formation: 59 passes, including 14 added v3 cancellation tests.
- Recovery: 11 passes; independently repeated with no failures/errors. Exact
  package fixture restored six original files and two original absences,
  preserved unrelated files, refused drift/later edits, and tolerated repeat
  rollback. No such operation targeted TESTS.
- Supported Smart Builds: 2,072 passes across 17 suites. Party Formations: 19;
  Hero Team Manager: 13. Shared authorization/reservation checks matched baseline.
- Inherited failures: Energy Surge PyCallback collection failure; 58 Mesmer
  composition failures; hex-profile cache 4 failed / 1 passed. No new suppression.
- Strict Pyright: new formation/support files clean; older owners 842 errors
  versus baseline 849, no added occurrences. Older Ruff diagnostics: 35 on both
  sides, no added occurrences. New files passed formatting/compilation checks.
- Native diagnostic: 20 offline regressions and strict Pyright/Ruff/Black checks
  passed. Startup diagnostic and its regression file are preserved; no fresh
  startup-test result is claimed by this parking task.

The native-diagnostic independent-review temporary directory exists but was
unreadable in this session. Its verdict is not inferred. That diagnostic still
requires an available independent safety-review result before any approved use.

## TESTS and native investigation

Read-only inspection found all eight formation release paths matching the
original preimplementation TESTS state, including absence of both formation
modules. The original HeroAI Actions widget retains SHA-256
`a9b8ddda5b0bd02b1d4619cf5a8f2b1c769f25d4732db903b19b77531b9cd831`.
Available recovery receipts describe external fixtures, not TESTS installations.
Option A is not currently installed. No deployment is recorded in this work;
current file state alone cannot establish every historical external action.
**Do not run the formation rollback installer.**

The only investigation diagnostic found in TESTS is
`Widgets/Coding/Debug/Py4GW/HeroAI Actions Startup Diagnostic.py`, byte-identical
to EDITS and untracked in TESTS. The native compatibility diagnostic and both
diagnostic regression files are absent from TESTS. No TESTS files were removed
or modified. Any removal of that single startup widget needs separate approval.

The user confirmed the existing TESTS DLL was loaded in Guild Wars. Its on-disk
SHA-256 was verified as
`4e5d25e18f4f941a49e85409eb2d946b7418daa0a8b6e1c4dbc33b17072beda1`.
A matching PDB was not located; exact native build provenance is unresolved.
No DLL was rebuilt/replaced, no native invitation was executed, and no live
client was operated by the diagnostic implementation or parking task.

Supported binding observations cover party players/heroes/henchmen, roster
consistency, local membership/leadership, map location, type and age. Native
source leaves `PyParty.others` unpopulated and excludes others from party size.
`PartyInfo.others_array` uses an unverified live ctypes pointer/layout/lifetime
contract; array-header checks occur after the initial pointer dereference.
`CharContext.token1`/`host` may supply stronger instance evidence, but their
deployed pointer contract also remains unverified. The standalone diagnostic
does not read either pointer path and never confirms complete solo eligibility.

Still unresolved: loaded native contract/layout, authoritative live eligibility
and exact outpost instance, reciprocal membership/intended leadership,
terminal-call/thread safety, cancellation during real delayed execution, and
synchronous safety-marker save latency. Guild halls remain unsupported. Shared
isolation-group retention after disbanding is inherited from manual joining and
is not repaired by Option A; independent-party interference remains a limitation.

## Safe continuation

1. Identify the saved checkpoint using the permanent `checkpoint.json` and
   verify the archive inventory. This checkpoint authorizes neither new feature
   work nor deployment; obtain the user's resumption direction first.
2. Recheck branch, working tree, index and saved work before any future change.
   The user controls the manual return to Personal/Builds. Do not hide, delete,
   stash or commit unrelated future work.
3. On eventual resumption, compare the parked source against the then-current
   Personal/Builds and TESTS environment. **Never overwrite newer TESTS shared
   files with the old v3 artifacts.** Reintegrate narrowly and repeat applicable
   compatibility and independent safety review before seeking fresh approval.
4. The archive is a checkpoint, not an installer authorization. Deployment and
   controlled live trial remain false until separately authorized after review.
