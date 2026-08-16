# Multibox shared-memory slot stability fix (HeroAI options regression)

Status: implemented and build-verified (2026). Live multibox run pending.

## Symptom (user reports)

- Repeated console logs: `Account <email> has no HeroAI options in shared
  memory, creating default options.`
- Followers suddenly stop combat/following/skills; accounts go inert until a
  restart/reload.
- Trigger correlates with script switches, manual leader takeover, and
  multibox launches.

## Root causes (source evidence)

1. **Non-atomic slot claims (the true migration regression).** The C++
   writer's `FindOrClaimAccountSlot` claimed empty/expired slots with plain
   reads and writes. The migration plan explicitly required the C++ side to
   make claims atomic (`multibox-shmem-cpp-writer-plan.md`, "C++ can make the
   claim atomic"), and the code left a NOTE that it was a follow-up. Two
   clients launching at the same time could both claim the same slot; each
   then bounces to another slot on later frames. Every bounce moves the
   account away from its `HeroAIOptions` entry.
2. **HeroAIOptions are index-anchored, not truly email-anchored.** The options
   array is a parallel array at the same slot index as `AccountData`
   (`AllAccounts.py`). "Email lookup" is an index lookup in disguise: any slot
   bounce leaves the account's options at the old index (now another
   account's slot) and hands the account stale options from the new index.
3. **Child-slot claims could evict account slots (legacy parity break).** The
   C++ `FindOrClaimChildSlot` used `allow_expired_reclaim=true`, while the
   legacy Python writer used `GetEmptySlot(allow_expired_reclaim=False)` for
   hero/pet claims. A hero/pet claim could therefore evict a stalled-but-alive
   account slot, bouncing that account.
4. **Per-frame torn-read window on the email anchor.** `WriteWideField` does
   wmemset-then-copy on `AccountEmail` every frame. Cross-process readers
   could observe an empty email mid-write, fail the slot lookup, and miss the
   options for that frame.
5. **Zeroed fallback struct (the visible killer, pre-existing).** The HeroAI
   `PartyCache` fallback created a plain `HeroAIOptionStruct()`, which is
   all-zeros: Following/Combat/Targeting/Looting/skills all off. The proper
   default is `reset()` (all enabled). This fallback existed in legacy too but
   was rarely reached; the slot churn above made it fire constantly.

## Fixes applied

### Python (`Py4GW_Reforged`)

- `Py4GWCoreLib/HeroAI/utils.py`: added `detached_hero_ai_options()`, a
  private byte-copy of a shared-memory options struct so cached "last valid"
  values can never silently become another account's options.
- `Py4GWCoreLib/HeroAI/party_cache.py`: keeps last valid options per account
  email (detached copies) and reuses them when shared-memory options are
  temporarily unavailable; on first miss it creates the struct and calls
  `reset()` (enabled defaults) instead of using a zeroed struct; the "no
  HeroAI options" log now fires at most once per account per session.
- `Py4GWCoreLib/HeroAI/cache_data.py`: `account_options` is now a detached
  copy; added `_republish_options_if_slot_changed()`, which detects when this
  account's resolved slot index changes (or first resolves) and republishes
  its last valid options at the new index. This re-anchors options after any
  C++ slot bounce and after region recreation, with no cross-account writes.

### Native (`Py4GW_Reforged_Native`)

- `src/GW/multibox/manager.cpp` + `include/GW/multibox/manager.h`:
  - Slot claims are atomic: `Key.HWND` is reserved with
    `InterlockedCompareExchange64` before the slot is filled (no layout
    change; the static_assert trip-wires are untouched).
  - `FindOrClaimChildSlot` now claims empty slots only (legacy parity); it can
    no longer evict a stalled account slot. Own-expired child slots are still
    reused via `FindChildSlot`.
  - `FindAccountSlot` prefers the slot carrying this client's own HWND key
    among duplicate email matches, self-healing old duplicate slots.
  - `AccountEmail` is written only when it changes, removing the per-frame
    wmemset torn-read window on all payloads.

## Ownership kept intact

- `HeroAIOptions` remains Python-written; C++ still never touches it after
  region creation (creator seeding unchanged).
- Byte layout unchanged: no new fields, `sizeof` static_asserts untouched.

## Verification run

- pyright 1.1.411 on the three changed Python files: 0 errors, 0 warnings.
- Native build: `cmake --build build --config RelWithDebInfo` (MSBuild
  17.12) recompiled `manager.cpp` and relinked `Py4GW.dll`, exit 0.
- Not verified here: live injected multibox run (requires the game and
  multiple accounts). Runtime confirmation steps: launch N boxes at the same
  time, switch the leader between scripts and manual control, and confirm the
  "no HeroAI options" log appears at most once per account per session and
  followers keep their toggles.
