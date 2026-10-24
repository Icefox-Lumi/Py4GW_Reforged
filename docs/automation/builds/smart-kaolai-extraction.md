# Smart Kaolai Extraction

Status: historical; current-source reconciliation dated 2026-10-24
Scope: My Blood is Power's first Smart Skill extraction and historical generic release restoration
Authority: original source/history and offline evidence below; reconciliation against committed source and tests at `9e160a794a95f09c90e965a5a8e05a175f7fd60f`

## Current Reconciliation (2026-10-24)

The sections from **Ownership** onward preserve the original extraction record,
including its then-current conclusions and offline-only verification scope.
Their present tense refers to that historical snapshot. The original full-bar
fallback mask and positive-identity prerequisite are superseded, not current
requirements. Historical evidence has not been rerun or re-dated here.

### Ownership and Matching

The dedicated [My Blood is Power controller](<../../../Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py>)
remains the single orchestration/action owner. Recognition requires primary
Necromancer, secondary Ritualist, and equipped PvE Blood is Power; the other
seven slots are flexible. The original exact-eight-skill requirement is
historical. Equipped locally handled skills remain masked from HeroAI even
when their local admission declines; supported replacements remain available
to fallback. The owner's pending protection also blocks fallback while an
accepted local action is pending.

[SmartKaolai](../../../Py4GWCoreLib/Builds/Skills/SmartKaolai.py) and
[SmartBloodIsPower](../../../Py4GWCoreLib/Builds/Skills/SmartBloodIsPower.py)
are dedicated owner-bound components, not additional schedulers or action
owners. Shared execution helpers and supported HeroAI fallback retain their
roles. Spirit Transfer and Spirit Light still use RestorationMagic; their
proposed Smart-module extractions are separate future milestones. See the
[BuildMgr/SkillsTemplate contract](buildmgr-and-skills-template.md) for shared
ownership boundaries.

### Routine and Adaptive Emergency Release

Both paths require a loaded party, no owner-local pending cast, and a generic
held-item indication. The controller invokes them only with Kaolai equipped.
Their census intersects the ally array with connected party players, heroes,
and henchmen; IDs must be distinct, positive, valid, and living under the
existing shared-aware checks. Assessment includes exactly 2,500 units; this
radius is not proof of actual healing reach. The caster counts only if eligible
in that intersection.

- Routine release retains four eligible recipients with strictly `0 < HP < 75%`.
  Its priority remains after Spirit Transfer below 30%, Spirit Light below 30%,
  and Mend Body and Soul below 40%.
- Adaptive emergency release requires at least two eligible recipients with
  strictly `0 < HP < 40%`. Only those recipients contribute to
  `sum(50% - HP) >= 30 percentage points`. This measures injury burden, not
  predicted healing. There is no three-person limit or four-person veto.
- After the existing `CanCast` gate, an early emergency attempt precedes those
  targeted heals. Any eligible recipient observed strictly below 20% in either
  the initial census or the validated health list defers this early attempt.
  Exactly 20% does not trigger that deferral. Accepted actions end the pass.
  If targeted rescue and routine release decline, a later emergency attempt
  recomputes evidence with `after_targeted_heals=True`; it does not reuse an
  earlier decision as permission to release.

Emergency evaluation first requires two below-40% recipients in the shared-aware
census and rejects more than 64 recipients. It then copies eligible remote
publication evidence. A matching agent/map-region-district-language/party record
must be active, represent an account, have a positive matching login, and retain
its timestamp and identity/context during the reread. It must be living, have
`0 < HP <= 1`, and pass the uint32 freshness check with age strictly below
250 ms; future/ambiguous timestamps are rejected. Competing matching records
are ambiguous and cannot authorize emergency release.

When a recipient has no matching remote record, including self, the helper
conditionally uses native/local `Agent.IsDead` and `Agent.GetHealth` instead.
Records for another map context or party are skipped. An invalid, stale, or
conflicting matching record is rejected without that native fallback. Thus not
every remote health observation is necessarily backed by a fresh publication.
Unavailable emergency evidence does not impose these extra requirements on
routine release or prevent the existing targeted-heal attempts.

Both paths retain the FrameTree Drop Bundle route `5040781, [0, 0]`, button
usability checks, and the owner's 250-ms pending stamp before yielding. An
accepted helper result means the Python click call returned. It does not prove
native execution, bundle release, or completed healing; `Frame.click()` can
decline at its final usability recheck.

### Option A, Provenance, and Accepted Limits

The explicit final user decision was **Option A: generic held-bundle admission**.
Positive Kaolai item-model identity, a required Kaolai effect, Vorizun identity
exclusion, item/effect stability waits, extra identity cooldowns, and native
dispatch callbacks are not requirements. The user accepted the possibility of
dropping another held bundle; that risk was neither statistically measured nor
eliminated. The manual held-item comparison is an observational development
tool, not an admission gate or identity guarantee.

Published milestones include Kaolai extraction (`52469274a`), adaptive emergency
release (`8f25191c4`), flexible matching (`318e06989`), SmartBloodIsPower extraction
(`14dd647fc`), and manual held-item diagnostics (`9e160a794`). The cleanup record
reports independent review of these completed milestones and completed practical
live Kaolai acceptance; this documentation checkpoint did not repeat either
review or live testing. It requires no additional Kaolai capture. That acceptance
does not attribute a battle victory or an HP rise to a particular release.

Current thresholds, publication handling, priority, matching, and pending
protection were checked against the committed source and
[Kaolai regressions](../../../tests/test_kaolai_release.py) and
[controller regressions](../../../tests/test_my_blood_is_power.py).
No gameplay regression suite was rerun for this documentation-only checkpoint.
The [historical observation record](smart-kaolai-observation.md) retains the
original execution/identity investigation, dated validation, and superseded
tactical proposal.

## Ownership

`Py4GWCoreLib/Builds/Skills/SmartKaolai.py` owns the specialized release decision
for `My Blood is Power.py`. The build constructs one helper after its match-only
exit and invokes release at the existing early priority and preparation at the
existing later priority. Diagnostic winners remain `Drop_Held_Bundle` and
`Protective_Was_Kaolai`.

The build retains orchestration, generation checks, cancellation, account
identity, pending timing, cast dispatch, coordination, and the full eight-skill
fallback mask. Smart Kaolai has no independent scheduler, queue, fallback,
timer, or global action state. Preparation delegates to the same
`RestorationMagic.Protective_Was_Kaolai` instance, preserving its holding,
skillbar, casting, energy, recharge, toggle, and owner-dispatch checks.

## Historical Generic Restoration

Commit `6ea32a6f` introduced Kaolai and drop-bundle support; `ba2f8d27` added the
FrameTree route. The restoration reverses the release-helper behavior added by
`d65d7df2`, using its exact parent
`1cf951e4a11776cdc6df6c0a8b5ddd8474ff69e8`.

`NoAttribute.Drop_Held_Bundle` again counts entries from the distance-filtered
ally array using shared-aware liveness and health. Its historical unused
`UIManager` import is not reintroduced. The FrameTree path `5040781, [0, 0]`,
button usability check, and 250 ms pending stamp before yielding are retained.

Stock callers deliberately lose the loaded-party and pending-admission gates,
connected-party roster intersection, duplicate elimination, explicit positive
and valid agent-ID checks, and explicit positive-health lower bound. Nonparty,
disconnected, repeated, or invalid entries can therefore contribute when the
remaining checks accept them. Shared-aware liveness still rejects dead or
nonpositive-health recipients. The helper stamps pending time but does not
itself reject a second call during that window; outer owners may still do so.

## Custom Parity and Ash Identity

Smart Kaolai retains the pre-extraction improved behavior: a loaded party,
pending suppression, connected players plus heroes and henchmen, intersection
with the original ally array, distinct positive valid IDs, shared-aware
liveness and health, and four recipients with strictly `0 < HP < 0.75` within
an inclusive 2,500 units. The caster counts only when already in that
intersection. A usable drop button and an existing held item remain required.

A successful result means only that the click call returned. The subsequent
[execution investigation](smart-kaolai-observation.md) establishes that even
native submission is not acknowledged by this interface. It does not prove
release or healing. Holding an item, having Kaolai equipped, a previous
cast submission, and an unverified buff do not positively identify Kaolai
ashes. Supported positive ash identification is a prerequisite for later
tactical emergency rules. This extraction introduces no two-critical-target,
single-recipient, expanded-range, or speculative identity policy.

## Offline Verification

`tests/test_kaolai_release.py` separates improved custom admission from the
intentional historical stock behavior. `tests/test_my_blood_is_power.py`
exercises real owner release and preparation, pending retries, cancellation,
lifecycle invalidation, reordered and disabled skills, diagnostic attribution,
and independent owner state. Existing Spirit Transfer, Spirit Light, BiP,
fallback, and diagnostic regressions remain in place.
`tests/test_bip_diagnostic.py` retains its diagnostic assertions and supplies
the new helper field on its partial-owner fixture using its existing skill stub.

The local extraction record under `.local-tests/smart-kaolai-extraction/`
contains the captured pre-extraction sources, exact parent helper, differential
tests, workspace hashes, and scoped strict Pyright comparison. Restoring the
historical untyped array-filter calls also restores their strict Pyright
diagnostics; the comparison reports these explicitly instead of suppressing
them. Offline tests do not establish native ash identity or completed healing.
