# Smart Spirit Light

Status: current; Stage 1 implementation, awaiting independent review
Scope: My Blood is Power's Spirit Light policy and historical shared admission restoration
Authority: production Python, committed baseline `f1406579f4fd19c0b6de21280b8c8cea25845bd3`, historical source, and offline tests

## Ownership and actual behavior

[SmartSpiritLight](../../../Py4GWCoreLib/Builds/Skills/SmartSpiritLight.py)
owns My Blood is Power's genuine-spirit admission, existing recipient selection,
health threshold, and accepted-heal reporting. The
[My Blood is Power controller](<../../../Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py>)
retains the priority rotation, lifecycle, pending state, fallback mask,
diagnostic lifecycle, and action dispatch through BuildMgr.

The emergency attempt remains strictly below 0.30. The ordinary attempt uses
`Conditions.LessLife or 0.60`, clamped to `[0, 1]`, with a strict comparison.
Recipient selection remains `ResolvePreferredAllyTarget` with the original
metadata and living/health validator. Its existing priority and spellcast
recipient range (1,248 units) remain intact, including self-healing.

Spirit availability uses `GetNearestSpirit(Range.Earshot.value)`, including the
1,012-unit boundary. The existing SpiritPet-array, range, liveness and spawned
filters define eligibility; no donor ownership, allegiance, health-ranking or
tactical rules were added. A pet alone, or only absent/dead/invalid/unspawned
entries, cannot authorize a Smart cast.

The old RestorationMagic helper contains a no-spirit sacrifice fallback, but
committed My BiP could not submit that fallback: BuildMgr's Spirit Light
exception required a genuine spirit anyway. The extraction preserves this
reachable behavior. Smart does not implement or enable the dormant sacrifice
fallback. Low caster health still permits spirit-supported healing, including
self-healing, exactly as before; it does not permit no-spirit admission.

## Revalidation and metadata

The execution path remains:

```text
MyBloodIsPower.ProcessSkillCasting (context and generation checks)
  -> BuildMgr skill-casting phase
  -> MyBloodIsPower._run_local_skill_logic
  -> SmartSpiritLight.try_cast (genuine spirit and recipient decision)
  -> owner.CastSkillIDAndRestoreTarget(extra_condition=genuine-spirit callback)
     -> CanCastSkillID (callback plus normal shared/resource checks)
     -> owner.CastSkillID
        -> CanCastSkillID (callback plus normal shared/resource checks again)
        -> target and coordination checks
        -> existing queued UseSkill, pending stamp, tick success
     -> RestoreEnemyTarget
  -> accepted-heal diagnostic submission
```

Unlike SmartSpiritTransfer, SmartSpiritLight does not alter any metadata.
`RequiresSpiritInEarshot` stays true in its owner's registry and in stock/global
metadata. A genuine spirit in earshot satisfies the generic living SpiritPet
gate, so no owner-local adaptation is needed. The additional callable rejects
pets as substitutes and is passed to both existing BuildMgr admissions.

Tests remove, invalidate, kill, or move the spirit after selection and between
wrapper and final admission, for self and other recipients, with and without a
remaining pet. Both the committed My BiP path and Smart reject submission.
The callback observations are Python checks, not a transaction with the game.
No atomic guarantee is made after the final observation or native queue
submission, and submission does not prove completed healing or sacrifice.

Resource, recharge, shared-toggle, slot lookup, weapon, other shared conditions,
target validation, coordination, duplicate prevention, and dispatch remain in
BuildMgr. Target restoration and the existing 250-ms aftercast are preserved.
New My BiP Spirit Light callers must use SmartSpiritLight to retain its stricter
policy; a direct generic cast API call does not include the Smart callback.

## Historical stock restoration and sacrifice consequences

Commit `423fda782b5240e25633a83115712d919fa636bd` added the Spirit Light-specific
genuine-spirit branch to `BuildMgr._meets_custom_skill_shared_conditions`.
Stage 1 removes only that exception and its now-unused `Skill` import. The
original generic gate again requires living SpiritPet-array entries within
earshot, without the spawned filter. The already restored stock Spirit
Transfer policy and unrelated BuildMgr behavior are preserved.

The stock RestorationMagic helper is unchanged. These are its actual outcomes,
assuming an eligible recipient and all other execution guards pass:

| Evidence at selection | Generic admission | Stock helper behavior |
|---|---|---|
| Genuine eligible spirit in earshot | Allowed | Normal selection, including self; no sacrifice-health floor required |
| Only a living pet in earshot | Allowed | No-spirit fallback can select another ally if caster HP is strictly above 0.30 |
| Only a living unspawned SpiritPet entry in earshot | Allowed | Same no-spirit fallback as pet-only input |
| No living SpiritPet entry in earshot | Rejected | No submission, even when the helper's health precheck passes |
| Only dead or invalid entries | Rejected under the existing liveness inputs | No submission |
| Spirit only beyond earshot | Rejected | No submission; unlike Transfer, spellcast donor range is insufficient |

The metadata's `SacrificeHealth = 0.30` is a caster-health admission floor,
not a statement that the game sacrifices 30% health. Exactly 0.30 fails the
no-spirit helper precheck. Without a genuine spirit at selection, the helper
copies metadata for `OtherAlly` targeting and excludes the caster; if self is
the only candidate, it declines.

Timing matters: if a genuine spirit enabled self-target selection and then
disappears, a living pet may still satisfy the generic gate. When caster health
is above 0.30, the stock helper's repeated health fallback can admit the already
selected self target. It does not reselect an other ally at that point. The
historical and restored paths are tested for this case; Smart rejects it.
Direct generic ID/slot admission also does not itself run the helper's
sacrifice-health precheck or other-ally selector.

The affected stock helper consumers are:

- `Py4GWCoreLib/Builds/Necromancer/N_Rt/Blood is Power Healer.py`: emergency and ordinary Light.
- `Py4GWCoreLib/Builds/Necromancer/N_Rt/Xinraes Weapon Healer.py`: emergency and ordinary Light.
- `Py4GWCoreLib/Builds/Ritualist/Rt_Any/SoS Healer.py`: its 0.60 Light attempt.

Restoration intentionally reopens their historically permitted sacrifice-capable
submissions. These are not equivalent to the pre-extraction special case.
HeroAI combat and SkillManager own separate admission paths; their source and
metadata are unchanged. My BiP keeps locally owned equipped skills masked from
HeroAI even when Smart admission declines.

## Lifecycle and evidence

The component retains only an owner reference and the optional existing
diagnostic reference. It has no scheduler, queue, timer, retained target, or
independent action ownership. Match-only construction does not instantiate it.
The controller attaches and clears its diagnostic with the other helpers.
Map, character, cache, invalid-context, disposal, and slot changes remain under
the existing generation and coroutine lifecycle. Closing suspended work cannot
cancel an already queued request.

`tests/test_smart_spirit_light.py` loads the committed controller and committed
BuildMgr together for before/after comparisons. The unchanged stock helper and
production targeting, checks, and submission methods execute against the
existing offline native/cache boundaries. It also loads the parent of the
historical correction to compare restored stock admission and helper outcomes.
Full rotation comparisons include armed/disarmed diagnostics, pending retries,
fallback masks, and Spirit Transfer priority. Existing Smart Kaolai, BiP,
Transfer, restoration, and diagnostic suites remain part of verification.

Local validation artifacts are under `.local-tests/smart-spirit-light-stage1/`,
using existing ignore rules. This evidence is offline; TESTS and the injected
client were not accessed. Independent Sol High review is the next checkpoint.

## Validation

On 2026-10-24, the complete pre-change baseline passed all 1,431 cases. The
final six-suite run passed all **1,560 cases in each collection order**
(150.50 seconds forward, 150.64 seconds reverse). The new suite contributes
129 cases. Run `python -B -m pytest -v -p no:cacheprovider <files> --tb=short`
with this file order, then its reverse:

1. `tests/test_restoration_spirit_admission.py`
2. `tests/test_my_blood_is_power.py`
3. `tests/test_kaolai_release.py`
4. `tests/test_bip_diagnostic.py`
5. `tests/test_smart_spirit_transfer.py`
6. `tests/test_smart_spirit_light.py`

The first full runs exposed a diagnostic fixture missing the existing Earshot
constant. Adding that boundary stub fixed all 372 diagnostic cases; both final
complete runs include the correction. Assertions and production guards were
not bypassed. Existing stock tests now assert historical admission explicitly;
committed-before/Smart-after tests preserve the customized rejection coverage.

Static verification on 2026-10-24 covers all seven changed Python files:

- Strict Pyright reports 227 errors and one warning, all inherited in BuildMgr.
  The pre-change and final diagnostics match by rule, message, source line and
  column after mapping the moved/dedented source. Zero findings were introduced
  or removed; no diagnostics were suppressed. The other six files are clean.
  The local strict config extends the project config, uses Windows/Python 3.13,
  and includes only the changed Python files. Reproduce with
  `pyright --project .local-tests/smart-spirit-light-stage1/pyrightconfig.json --outputjson`.
- `python -m ruff check --output-format=json <changed-python-files>` reports the
  same 17 inherited BuildMgr findings: nine F401 and eight E731. Zero additions.
- Individual `python -m black --check --diff <file>` checks pass six files.
  Whole-file BuildMgr formatting fails before and after; the changed admission
  method passes a non-writing Black comparison. No formatter rewrote source.
  A multi-file Black attempt encountered the Windows process-permission limit;
  individual-file reruns completed.
- In-memory compilation of all seven Python files, relative documentation
  links, and `git diff --check` pass.

## Review file set and preservation

The exact changed and independent-review file set is:

- `Py4GWCoreLib/BuildMgr.py`
- `Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py`
- `Py4GWCoreLib/Builds/Skills/SmartSpiritLight.py` (new)
- `tests/test_restoration_spirit_admission.py`
- `tests/test_my_blood_is_power.py`
- `tests/test_bip_diagnostic.py`
- `tests/test_smart_spirit_light.py` (new)
- `docs/automation/builds/README.md`
- `docs/automation/builds/smart-spirit-transfer.md`
- `docs/automation/builds/smart-spirit-light.md` (new)

The workspace started clean on `Personal/Builds` at
`f1406579f4fd19c0b6de21280b8c8cea25845bd3`. Branch, HEAD and index are preserved.
No staging, commits, pushes, deployment, ignore-rule changes, or access to TESTS
occurred. SmartSpiritTransfer, SmartKaolai, SmartBloodIsPower, stock
RestorationMagic, and shared skill metadata remain unchanged. Transfer's review
record only receives a status and cross-reference update. The nearest README
is updated; the current human-maintained documentation index needs no top-level
route change.
