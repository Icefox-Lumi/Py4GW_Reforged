# Native Account Publication

Status: current; offline-verified, pending injected-client verification
Scope: corrected Native account evidence and the detached Python reader
Authority: Native multibox source, Python ctypes declarations, focused regression tests

## Transport and ownership

The compatibility mapping `Py4GW_Shared_Mem` remains v1. Existing
`GetAllAccounts()`, Submit, reset, debug writers, and Python coordination use
that mapping. Corrected evidence uses `Py4GW_Shared_Mem.v2` and the session
mutex `Local\Py4GW.AccountPublication.v2`. The legacy managers reject the v2
name, including its equivalent `Local\` spelling.

Native captures current game data directly into zero-initialized private
storage. It never copies v1 evidence into v2. Future consumers must use the
detached v2 API and must not join the mappings by slot index. Stage 3 role
recognition and composition are outside this change.

The packed layout remains unchanged. Native owns `Keys`, each account's
prefix before `IsIsolated`, and `LastUpdated` separately. It preserves the
embedded isolation/aggro fields, Inbox, HeroAIOptions, and Intents during
publication, retirement, reuse, and recovery. Those reserved v2 bytes do not
form another coordination system; the Python reader clears them in its
detached evidence copies. Python coordination remains v1.

Native spans use `offsetof` and layout assertions. The reader derives its
prefix and spans from actual ctypes offsets and compares them with Native
metadata before accepting bytes.

## Publication and leases

Game reads and lifecycle/identity/roster revalidation precede the publication
lock. Hero roster position `i` uses skillbar position `i + 1`; filtering by
ownership preserves the original position. Missing or mismatched bars retain
no previous skill IDs. Player and controlled-agent identities must agree.

One nonblocking lock protects slot allocation, expiry checks, consistent
Keys/AccountData identity, obsolete-child retirement, and the entire owner
plus child publication. Every member gets one common uncached Windows boot
tick. Pets use entity type 2, LocalIndex 0, scoped by owner email and HWND;
the current pet agent ID remains in AgentData.

A fresh same-email publisher with another HWND cannot be taken over. Safe
expired reuse updates both HWND copies and retires the former owner's
children. Inactive reservations are reclaimable. Capacity, duplicate-key,
invalid-capture, or allocation failure retires the affected owner's usable
evidence without publishing a partial usable roster. Loading publishes only
unusable owner identity and retires children.

Age is `(now32 - LastUpdated) & 0xFFFFFFFF`. Age 4999 is live, 5000 is expired,
zero timestamps are valid, and age at least `0x80000000` is rejected as
future or ambiguous. Such an age does not authorize eviction. The same Python
helper corrects existing v1 lease/order decisions in AllAccounts,
SmartEnergySurge, and My Healing Burst; those skills continue to consume v1.

## Snapshot and shutdown contract

`Py4GWSharedMemoryManager.GetNativeAccountSnapshot()` returns a typed
`AccountPublicationResult`: status, optional reason, and optional
`NativeAccountSnapshot`. Statuses are success, busy, unavailable, recovery,
and sync_failure. Every failure has `snapshot=None`; there is no cached or
v1 fallback. A successful empty snapshot contains no usable evidence.

Each snapshot stores a tuple of immutable `NativeAccountEvidence` byte
records. `GetAccountData()` decodes a fresh Python-owned ctypes copy. No
mapped memoryview, `from_buffer` object, or nested live mapped array escapes.
The reader validates keys, activity/type, lease, duplicate identities,
owner/child relationship, and a common cohort tick. Invalid children reject
their cohort; orphan children are excluded.

Busy publication changes no bytes or heartbeat. Abandoned-mutex acquisition
gives the caller ownership: it clears all Native evidence while preserving
coordination, releases normally, and returns recovery without a snapshot or
replacement publication. Subsequent calls can repopulate normally. Transport
or synchronization failures return no evidence.

Attachment establishes the mapping handle and full view before acquiring the
publication mutex. No shared bytes are trusted, initialized, or mutated before
that acquisition. Failed mapping creation or view attachment never acquires
the mutex, so it cannot consume abandonment without repairing the table. A
caller with valid mapping access repairs abandoned evidence under the mutex
before releasing it. New pagefile mappings start zeroed by Windows; concurrent
attachments still acquire the same mutex before accepting the mapping.

A local Native mutex guards mapping handles, publication, snapshot copying,
and destruction. Python conversion occurs after both locks are released.
Normal explicit shutdown waits for this local lifetime guard, protecting any
active snapshot copy, then attempts cross-process retirement with a zero-timeout
acquisition. If the publication mutex is busy, shutdown stops publishing,
closes its local view safely, and leaves lease expiry to remove visibility.

Static destruction uses a single nonblocking attempt at the local lifetime
guard instead of the ordinary `Destroy()` path. If unavailable, it performs no
manual retirement, unmap, or handle close; process termination leaves resource
reclamation to Windows. If obtained, it uses the same zero-timeout publication
acquisition and guarded cleanup. The runtime manager's destructor does not
call blocking publication destruction. Explicit orderly unload retains normal
`Destroy()` synchronization; `DLL_PROCESS_DETACH` during process termination
skips that explicit shutdown path. Static fallback does not guarantee evidence
retirement or manual resource cleanup.

Lock order is always local lifetime protection followed by the nonblocking
publication mutex: attachment, snapshot, publication, recovery, and ordinary
destruction follow this order. Static fallback first tries the local guard,
then uses the same order if successful. No path holding the publication mutex
waits for a local lifetime guard.

## Verification and remaining boundary

Native tests in the sibling project's `tests/multibox_publication_tests.cpp`
exercise production allocation, transport, recovery, and lifetime code. Enable
`PY4GW_BUILD_MULTIBOX_TESTS` and build `multibox_publication_tests`. Set
`PY4GW_RUNTIME_OUTPUT_DIRECTORY` to keep artifacts separate from a deployed
DLL. Python regression coverage is in `tests/test_account_publication.py`,
plus the existing shared-memory, Energy Surge, and Healing Burst tests.

The eight Native regression groups include actual Win32 mapping-creation and
view-attachment failures after interrupted owner-only publication, subsequent
reader/attacher recovery, first-client zeroing, simultaneous attachment, and
normal snapshot/destruction safety. A separate test child runs the actual
static publication destructor with an orphaned local mutex; its parent enforces
a test-only deadline. Production teardown has no spin wait or timeout.
The corrective build uses `artifacts/account-publication-v2-r2/Py4GW.dll`;
the rejected `account-publication-v2` artifact remains intact for comparison.

Offline checks prove the protocol and ownership boundaries, not the live
validity of every game pointer or lifecycle transition. Real injection,
reconnect, map loading, account-anchor identity, snapshot cost, and shutdown
timing still require injected-client evidence. The latched/INI anchor behavior
is preserved and is not absolute proof of current logged-in account identity.
