# Smart Spirit Transfer

Status: current; Stage 1 committed as `f1406579f4fd19c0b6de21280b8c8cea25845bd3`
Scope: My Blood is Power's Spirit Transfer extraction and historical stock admission restoration
Authority: production Python, history through `6306a9a34e6734bed7a2f10f50a128e0885f39d0`, and offline regression evidence

## Ownership and admission

[SmartSpiritTransfer](../../../Py4GWCoreLib/Builds/Skills/SmartSpiritTransfer.py)
owns My Blood is Power's donor admission and recipient decision. The
[controller](<../../../Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py>)
remains the action owner and invokes the component at the existing emergency
and ordinary positions. No tactical priority changes are introduced.

The emergency threshold remains strictly below 0.30. The ordinary threshold
remains `Conditions.LessLife or 0.50`, clamped to `[0, 1]`, with a strict
comparison. Recipient selection still uses `ResolvePreferredAllyTarget`, its
existing metadata, candidate priority, and spellcast range, including self.
The donor check still uses `GetNearestSpirit(Range.Spellcast.value)` (1,248
units): the existing distance/liveness/spawned filters are unchanged. It does
not introduce an ownership, allegiance, or donor-health ranking requirement.

The production path is:

```text
MyBloodIsPower.ProcessSkillCasting (context/generation guard)
  -> BuildMgr.ProcessSkillCasting / _process_skill_casting_phase
  -> MyBloodIsPower._run_local_skill_logic
  -> SmartSpiritTransfer.try_cast
  -> owner.CastSkillIDAndRestoreTarget(extra_condition=Smart donor callback)
     -> CanCastSkillID -> extra_condition -> shared conditions
     -> owner.CastSkillID
        -> CanCastSkillID -> extra_condition -> shared conditions
        -> target/coordination validation -> existing queued UseSkill
        -> pending stamp / tick success
     -> RestoreEnemyTarget
  -> accepted-heal diagnostic submission
```

A Smart precheck alone cannot replace the downstream shared earshot gate.
`BuildMgr.GetCustomSkill` creates a separate `CustomSkillClass` per BuildMgr
instance. That registry constructs separate `CustomSkill` and `CastConditions`
objects. Smart construction permanently sets only this owner's Spirit Transfer
`RequiresSpiritInEarshot` field to false. This is owner-local configuration for
the component's lifetime, with no temporary changes or restoration dance.
The global HeroAI registry, stock builds, and source metadata retain the flag.

Every Smart attempt supplies the existing callable `extra_condition` interface
to `CastSkillIDAndRestoreTarget`. Both admissions invoke it again, so donor loss
after selection or between wrapper admission and final cast admission rejects
submission. The rest of BuildMgr's checks are untouched, including resources,
recharge, slot lookup, shared toggles, weapon and other shared conditions,
target validation, coordination, pending prevention, and dispatch. The normal
250-ms aftercast and target restoration remain owned by BuildMgr.

The owner-local metadata entry alone is not a donor gate. New My BiP callers
must use SmartSpiritTransfer; an arbitrary direct call to that owner's generic
cast API without the callback would lack the donor requirement. The two
production rotation sites are explicitly routed through Smart, and locally
owned equipped skills remain masked from HeroAI fallback. This adaptation
does not add a generic extension interface, override shared methods, copy
BuildMgr checks, or create another action queue.

## Historical stock restoration

Commit `74259a5e228ee3f56be300f6627785b96c5fa597` added the Spirit Transfer
exception in `BuildMgr._meets_custom_skill_shared_conditions`. Stage 1 removes
only that exception. Transfer again uses parent
`d65d7df2db1804bdf0fa787e066bb516045e3830`'s living SpiritPet-array check within
earshot (1,012 units). At the Transfer checkpoint, the later Spirit Light
exception from `423fda782b5240e25633a83115712d919fa636bd` remained intact. Its
subsequent restoration is documented in [Smart Spirit Light](smart-spirit-light.md).
Unrelated shared improvements and the stock RestorationMagic helper are unchanged.

The affected stock helper consumers are:

- `Builds/Necromancer/N_Rt/Blood is Power Healer.py`: emergency and ordinary Transfer.
- `Builds/Necromancer/N_Rt/Xinraes Weapon Healer.py`: emergency and ordinary Transfer.
- `Builds/Ritualist/Rt_Any/SoS Healer.py`: its 0.50 Transfer attempt.

Their behavior intentionally changes: a genuine donor only between earshot
and spellcast range no longer suffices for admission. Direct generic BuildMgr
ID/slot callers once again accept living pets/unspawned SpiritPet entries in
earshot. These are admission results, not evidence of a successful game cast.
The stock helper still first requires a genuine donor within spellcast range,
so pet-only input does not make that helper submit. A pet in earshot plus a
genuine donor farther out satisfies the two historical checks. Conversely,
the generic gate does not guarantee a genuine donor remains after selection
if a pet still satisfies it. My BiP's Smart callback retains that revalidation.

HeroAI combat and SkillManager have their own admission paths and unchanged
metadata; they do not use the altered BuildMgr branch. Their generic behavior
is not changed by this restoration.

## Lifecycle and verification

The component holds only its owner reference and the existing optional
diagnostic reference. Match-only construction creates no component or skill
registry. The controller attaches and clears the diagnostic alongside its
other helpers. It retains all context, generation, skillbar, pending, fallback,
and disposal ownership. Closing suspended work cannot retract an already
submitted native queue request. Accepted-heal reporting preserves the existing
meaning: Python accepted submission, not confirmed casting or completed healing.

`tests/test_smart_spirit_transfer.py` compares real pre-extraction controller
and BuildMgr code from the pinned HEAD with the new Smart submission path. It
also covers the stock consumers and real metadata registry isolation.
`tests/test_restoration_spirit_admission.py` records historical generic
admission separately from stock-helper filtering. The controller and diagnostic
suites exercise the integrated rotation and lifecycle. Validation artifacts
are local-only under `.local-tests/smart-spirit-transfer-stage1/`.

Validation on 2026-10-24:

- All **1,431 cases passed in each collection order**. Run
  `python -B -m pytest -q -p no:cacheprovider <files> --tb=short`, first with
  `tests/test_restoration_spirit_admission.py`, `tests/test_my_blood_is_power.py`,
  `tests/test_kaolai_release.py`, `tests/test_bip_diagnostic.py`, and
  `tests/test_smart_spirit_transfer.py`; then reverse that file order.
- The new suite contributes 47 cases, including pinned production parity,
  stock consumer submission, isolated production registries, donor loss,
  other shared gates, and suspended-work lifecycle/fallback protection.
- Scoped strict Pyright on all seven changed Python files reports the same
  227 errors and one warning as the five-file pre-change baseline. A comparison
  mapping unchanged source lines confirms zero added or removed diagnostics;
  both new files are clean. No diagnostics were suppressed.
- Ruff reports the same 17 pre-existing findings, with zero additions.
- Black passes six changed Python files and the edited BuildMgr admission
  method. Whole-file BuildMgr formatting fails both before and after; that
  unrelated formatting debt was preserved. Individual-file, no-cache checks
  avoided the multi-file runner's Windows process-permission failure.
- Compilation of all seven Python files, relative documentation links, and
  `git diff --check` pass. The initial baseline test run was interrupted, and
  its verbose rerun reached 61% before its 90-second timeout; neither is
  represented as a complete baseline pass. The final full runs took about
  127 seconds each and completed successfully.

This is offline verification. No TESTS runtime, injected client, native memory,
network, deployment, or live healing was exercised. SmartKaolai and
SmartBloodIsPower are unchanged. The subsequent
[SmartSpiritLight milestone](smart-spirit-light.md) has its own implementation
and evidence; the counts above remain the historical Transfer validation results.

## Review file set and preservation

The exact review set is:

- `Py4GWCoreLib/BuildMgr.py`
- `Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py`
- `Py4GWCoreLib/Builds/Skills/SmartSpiritTransfer.py` (new)
- `tests/test_restoration_spirit_admission.py`
- `tests/test_my_blood_is_power.py`
- `tests/test_bip_diagnostic.py`
- `tests/test_smart_spirit_transfer.py` (new)
- `docs/automation/builds/README.md`
- `docs/automation/builds/smart-kaolai-extraction.md`
- `docs/automation/builds/smart-spirit-transfer.md` (new)

The workspace started clean on `Personal/Builds` at the pinned HEAD above.
Branch, HEAD, and index are preserved. No staging, commits, pushes, deployment,
ignore-rule changes, or access to the protected TESTS workspace occurred. The
nearest README is updated; the current human-maintained documentation index
needs no top-level route change. This milestone subsequently completed independent
review and was committed as `f1406579f4fd19c0b6de21280b8c8cea25845bd3`, as recorded
in the Spirit Light task's user-provided checkpoint.
