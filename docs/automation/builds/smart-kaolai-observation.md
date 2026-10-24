# Smart Kaolai Missed-Drop Observation

Status: historical; tactical proposal superseded by the reviewed Option A implementation
Scope: My Blood is Power decision evidence and bounded, opt-in release observation
Authority: source/native inspection and offline tests at the investigation stage; current-source reconciliation dated 2026-10-24

## Current Status (2026-10-24)

The sections from **Findings** onward preserve the original investigation,
including its 2026-10-19 validation, execution caveats, capture design, and
then-proposed next step. Their present-tense descriptions and test totals refer
to that earlier snapshot, not fresh tests or the complete current rotation.
The original record did not verify live encounters or the deployed DLL.

At published checkpoint `9e160a794a95f09c90e965a5a8e05a175f7fd60f`, the
[current contract and source links](smart-kaolai-extraction.md#current-reconciliation-2026-10-24)
describe the completed adaptive emergency release, routine priority, conditional
publication/native health evidence, flexible BiP matching, and dedicated Smart
modules. In particular, the historical four-recipient rule below describes the
routine path; it is not the sole current release admission. Early emergency
release may now precede targeted healing, with the strictly-below-20% rescue
deferral and fresh later reconsideration described in that reconciliation.

The final proposal to establish positive ash identity before tactical changes
was superseded by the explicit **Option A** decision. Generic held-bundle
admission intentionally accepts the possibility of dropping a different bundle.
No Kaolai effect, model identity, Vorizun exclusion, stability wait, identity
cooldown, or native callback is required. The separate manual held-item
comparison is observational; it is not the armed 60-second capture described
below and does not control admission.

Practical live Kaolai acceptance is complete according to the cleanup record;
no further Kaolai capture is required. The historical limits on release/healing
attribution remain: acceptance does not prove that a particular release caused
an HP rise or battle victory. No new live observation or gameplay regression
run is claimed by this documentation reconciliation.

## Findings

Source inspection establishes possible reasons for a missed drop. It cannot
assign a cause to the reported encounters: their supplied summaries contain
request counters and damage observations, without a simultaneous qualifying
party census or a release receipt. The user's report that the extraction
passed review and reached TESTS is context, not a verification performed here.

`SmartKaolai.Drop_Held_Bundle` requires a loaded party, no local pending cast,
a generic held-item indication, and four distinct qualifying recipients.
Recipients must be connected players, heroes, or henchmen already in the ally
array, with positive valid IDs, shared-aware liveness, strictly
`0 < HP < 0.75`, and distance at most 2,500. The caster counts if present in
that intersection. The first frame at `5040781, [0, 0]` must be usable.

The custom rotation first checks `CanCast`, then tries Spirit Transfer below
30%, Spirit Light below 30%, and Mend Body and Soul below 40%. Each accepted
request ends the pass before the drop branch. These are separate helper
admissions, including their existing spirit, sacrifice, targeting, and cast
checks; a low HP observation does not guarantee any particular heal succeeds.

| Situation | Source-backed behavior |
|---|---|
| Two or three critical living allies, fewer than four injured | Fails the routine count regardless of how low their HP is. |
| Injured allies plus dead teammates | Dead teammates do not contribute. |
| Injured allies beyond 2,500 | Do not contribute; exactly 2,500 remains included. |
| Critical BiP | Counts as one qualifying recipient if in the census. An accepted earlier self-heal can preempt release. |
| Repeated accepted emergency heals | Can keep ending consecutive passes before drop consideration; no drop fairness rule exists. |
| Held indication but absent/unusable button | Helper returns false without clicking. |
| Pending action | Drop helper declines during pending protection. The read-only observer never stops or resets that timer. |
| Dead/invalid client, lifecycle change, cancelled pass | Owner processing or generation checks can prevent entry/completion. A click already called is not retracted by closing its generator. |

## Identity and Execution Boundary

`Agent.IsHoldingItem` reads `living.weapon_type == 0`; absence of a living
agent returns false. This is a generic indication, not a Kaolai identifier.
`GetWeaponExtraData` exposes weapon/offhand IDs and types, but the inspected
source provides no verified mapping from those values to the current Kaolai
bundle. Effect skill IDs, an equipped skill, and an earlier preparation request
also do not establish the identity of the item now held.

The related native project's `include/GW/context/Item.h` contains an inventory
bundle pointer. No supported Python bundle getter and verified Kaolai item
identity were established in the inspected Inventory/Item facades, stubs,
context facades, or item bindings. This finding is limited to the inspected
surfaces; it is not a claim that native identification is impossible. No raw
pointer access, native change, or speculative identity inference was added.

The execution path is:

1. Smart Kaolai checks the first drop frame and calls `Frame.click()`.
2. `Frame.click()` checks usability again and can return without doing anything.
   Usability means existing, created, and visible, not game acceptance.
3. If usable, it calls `PyUIManager.UIManager.button_click(frame_id)`.
4. Native `src/GW/ui/ui_bindings.cpp` enqueues work for the game thread and
   returns true unconditionally. Its queued lambda discards `ButtonClick`'s result.
5. `src/GW/ui/ui_methods.cpp::ButtonClick` checks frame/parent creation and
   sends a `kMouseClick2` frame message. Its boolean is not a completed
   bundle-release or party-healing receipt.
6. The Python helper stamps its existing 250 ms pending interval, yields, and
   returns true when resumed.

Consequently, the instrumentation says `click_call_returned`, not "confirmed
queued", "released", or "healed". A regression executes the real `Frame.click`
method with a failed final usability recheck and proves that the helper can
still return true without invoking the native button binding.

A later generic held flag changing from the helper's true indication to
false is additional evidence, but not a release receipt or ash identity.
Manual release, expiration, death, replacement, and session transitions must
be treated as possible alternative explanations or observation gaps. Their
specific effects on this flag were not verified live. Replacement or a rapid
release/recast may also occur entirely between samples while the flag appears
unchanged. An unchanged flag cannot prove a failed click.

`stubs/PyAgentEvents.pyi` exposes healing and current-health events.
Native `src/listeners/agent_events_listener.cpp::OnGenericModifier` publishes
positive healing/lifesteal with receiver, source, and magnitude but no skill
ID. The combat-event helper's pending-skill association is not an authoritative
Kaolai attribution. HP fraction rises can reflect other healing, regeneration,
or maximum-health changes. No verified API receipt for completed Kaolai party
healing was established. No event consumer or buffer-draining read was added.
The running DLL's correspondence to this native checkout remains unverified.

## Temporary Capture

Use the existing **Arm one capture** control in the Smart BiP Diagnostic
widget. The selected custom owner claims it on an aggro decision. Ordinary
disarmed operation performs no new census or diagnostic logging. No new
widget, writer, scheduler, skill request, or coordination write is introduced.

`SmartKaolai.py` owns the census and watch accounting.
`My Blood is Power.py` lends the existing capture and read-only pending/busy
observations, and retains action/lifecycle ownership. `BipDiagnostic.py`
provides its existing sampling admission, clock, and console output.

Bounds are unchanged at 60 seconds, at most four decision-entry samples per
second, and at most eight console records: START, up to six cumulative AGG
records, and DONE. Kaolai fields append to AGG/DONE. Each census inspects at
most 64 raw roster entries; larger rosters are marked incomplete. This cap
affects diagnostics only. One release watch may be open at a time, lasting
two seconds from its first click call, with at most four watches per capture.
Overlapping retries are counted without extending the deadline.

The widget's existing clock update can expire a watch while combat processing
is suspended. It does not read agents. There are no follow-up samples during
such a gap, death, or another owner gate that prevents decision entry.

| Evidence | Interpretation |
|---|---|
| `last_entry` | Latest sequential census: generic held indication; completeness; injured/critical/dead/outside/missing counts; four-person threshold; button, pending, busy, and self HP. It is not an atomic server snapshot. |
| `routine_entry` | Sampled entry met the current count, held, button, pending and busy conditions. Not proof that a later helper call saw the same state. |
| `critical2or3_below4` | Two or three recipients below the existing 30% emergency observation boundary, with fewer than four below 75%. No new tactical rule. |
| `routine_entry_preempted_*` | That same completed pass selected an earlier emergency heal. A delayed outcome remains associated only with its entry census. |
| `delayed_pass_outcome` / `inconclusive_cancelled_pass` | Outcome arrived after 250 ms / a sampled unfinished pass was abandoned on a new entry. No intervening duration is inferred. |
| `drop_checked`, `below_threshold`, `pending_or_party_gate`, `button_unavailable` | Counters at the actual helper's existing branches, including unsampled passes while capture is active. |
| `click_call_returned` / `drop_selected` | Click call and pending stamp happened / the rotation later accepted the returned result. Cancellation can leave only the former. |
| `generic_held_cleared` | A valid follow-up within two seconds read false. Not confirmed ash release. |
| `hp_fraction_rises_unattributed` | Distinct recipient rises per watch relative to a fresh entry sample, summed at watch end. Not a count of heals or healing attributable to Kaolai. |
| `no_change_observed` | At least one valid follow-up, without a false held indication. Does not prove continuity throughout the window or failed execution. |
| `inconclusive_*`, `overlapping_calls`, `window_budget_exhausted` | Context loss, no samples, early capture ending, ambiguous overlapping requests, or exhausted observation budget. |

The watch continues after a held-state change so a later HP observation within
the same window can still be recorded. If no entry sample is fresh enough at
the click call, HP comparison has no baseline. Zero rises therefore does not
prove absence of healing. All summaries state `identity:unknown`,
`click_receipt:unavailable`, and `heal_receipt:unavailable`.

The existing DONE `result` still describes the BiP capture. In particular,
`INCONCLUSIVE_NO_RELEVANT_DEMAND` refers to BiP energy demand and can coexist
with useful Kaolai evidence. `COMPLETE` never certifies release or healing.

## Verification and Tactical Follow-Up

Focused tests cover the real owner/helper/frame path, census boundaries,
repeated emergency preemption including self-heals, missing buttons, pending,
cancellation, lifecycle invalidation, held-state changes, unchanged flags,
death, observation gaps, output/sampling/window limits, and unknown bundles.
Armed/disarmed scenarios preserve skill requests, click counts, and pending
stamps; observation failure does not cancel gameplay. Coordination-write
guards and existing generic/Smart regressions remain in place.

The local `.local-tests/smart-kaolai-observation/` record retains the pre-change
sources and hashes, focused verification output, and strict Pyright comparison.
Validation on 2026-10-19 passed 799 focused regressions, 110 extraction
differential cases, and three current action/lifecycle source comparisons
(912 total). Scoped strict Pyright reported zero diagnostics before and after;
Ruff, per-file Black checks, and whitespace checks passed. The workspace hash
comparison found only the seven intended existing files changed, plus this
new investigation record.
The earlier extraction's executable differential regressions remain applicable;
its two whole-source AST equality checks describe the extraction-only snapshot,
so current action-body equality is checked separately after removing diagnostic
event calls. No generic helper, shared memory, HeroAI, DLL, or TESTS deployment
was changed by this observation task.

Proposed next step: first establish positive Kaolai identity and inspect armed
captures. Then evaluate a narrow two-or-three-critical-recipient emergency
branch before Spirit Light and emergency Mend Body and Soul. Preserve an
earlier Spirit Transfer when its target needs the immediate single-target
rescue and an eligible spirit exists. Compare urgency, recipient benefit,
caster survival, and release reliability before choosing thresholds; do not
simply move all routine four-person drops above Transfer. No threshold or
priority change is implemented here.
