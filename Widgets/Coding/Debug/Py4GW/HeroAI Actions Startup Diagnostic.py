"""Temporary, on-demand account evidence for the HeroAI Actions startup investigation.

Capture immediately when usable, then at labelled observation points. Startup,
command completion and party synchronization have no assumed fixed deadline.
Use a separate fresh-start wait-only control before the manual-party experiment.
Compare the full (map, region, district, language) location. Tokens belong only
to this diagnostic instance; slots can be reused. Authorization failure alone
does not prove isolation rejection, especially during publication changes.

Loaded production getters may populate frame/agent lookup caches. Reads require
loaded dependencies and existing attachments; native pointer lifetime and
concurrent service teardown still require live-runtime verification.
"""

# pyright: strict

from __future__ import annotations

import ctypes
import hmac
import secrets
import sys
from collections import Counter
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import TYPE_CHECKING
from typing import Callable
from typing import TypeVar
from typing import cast

import PyImGui
import PySystem

if TYPE_CHECKING:
    from Py4GWCoreLib.GlobalCache.GlobalCache import GlobalCache
    from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct import AccountStruct
    from Py4GWCoreLib.GlobalCache.shared_memory_src.AllAccounts import AllAccounts
    from Py4GWCoreLib.HeroAI.command_api import HeroAICommandAPI
    from Py4GWCoreLib.Map import Map
    from Py4GWCoreLib.Player import Player
    from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import WidgetHandler

MODULE_NAME = "HeroAI Actions Startup Diagnostic"
MODULE_ICON = "Assets/Textures/Module_Icons/HeroAI.png"
OPTIONAL = True

_PREFIX = "HA_STARTUP"
_MAX_SLOTS = 64
_MAX_LINES = 96
_MAX_LINE_LENGTH = 640
_UINT32_MASK = 0xFFFFFFFF
_secret: bytes | None = None
_previous_tokens: set[str] = set()
_baseline_number = 0
_capture_number = 0
_status = "Idle. Nothing is sampled until Capture Snapshot is pressed."
_T = TypeVar("_T")
# Audited TESTS call chain: Player -> Map/Agent -> AgentArray/UIManager ->
# native AgentArray -> SystemShaMemMgr. These imports occur inside getters.
_MAP_DEPENDENCIES = (
    ("Py4GWCoreLib.Map", "Map"),
    ("Py4GWCoreLib.Context", "GWContext"),
    ("Py4GWCoreLib.py4gwcorelib_src.FrameCache", "FRAME_CACHE"),
)
_PLAYER_DEPENDENCIES = _MAP_DEPENDENCIES + (
    ("PySystem", "Console"),
    ("PyUIManager", "UIManager"),
    ("Py4GWCoreLib.Player", "Player"),
    ("Py4GWCoreLib.Agent", "Agent"),
    ("Py4GWCoreLib.AgentArray", "AgentArray"),
    ("Py4GWCoreLib.UIManager", "UIManager"),
    ("Py4GWCoreLib.native_src.context.AgentContext", "AgentArray"),
    ("Py4GWCoreLib.native_src.ShMem.SysShaMem", "SystemShaMemMgr"),
)


def _attempt(read: Callable[[], _T], dependencies: tuple[tuple[str, str], ...] = ()) -> tuple[_T | None, str]:
    if any(_loaded(module, member) is None for module, member in dependencies):
        return None, "dependencies_unavailable"
    try:
        return read(), "none"
    except Exception as error:
        # Exception messages/tracebacks can contain account names and emails.
        return None, type(error).__name__[:48]


def _token(identity: str) -> str:
    if not identity:
        return "empty"
    if _secret is None:
        raise RuntimeError("Capture secret is unavailable")
    return hmac.digest(_secret, identity.encode("utf-8"), "sha256").hex()[:12]


def _clock() -> int:
    # The frame-cached PySystem clock can precede another client's publication.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    read = kernel.GetTickCount64
    read.argtypes = ()
    read.restype = ctypes.c_ulonglong
    return int(read())


def _age(now: int | None, stamp: int) -> int | None:
    if now is None:
        return None
    elapsed = (now - stamp) & _UINT32_MASK
    return elapsed if elapsed < 0x80000000 else None


def _key(account: AccountStruct) -> tuple[str, int, int]:
    return account.AccountEmail, int(account.SlotNumber), int(account.AgentData.AgentID)


def _loaded(module_name: str, member: str) -> object | None:
    module = sys.modules.get(module_name)
    if module is None:
        return None
    # A present symbol is not proof that module initialization has completed.
    # Also reject lazy modules: a transitive `from ... import` can probe __path__.
    value = vars(module).get(member)
    for candidate in (module, value):
        if isinstance(candidate, ModuleType):
            namespace = vars(candidate)
            spec = namespace.get("__spec__")
            if "__getattr__" in namespace or (isinstance(spec, ModuleSpec) and vars(spec).get("_initializing")):
                return None
    return value


def _scan(registry: AllAccounts, account_type: type[AccountStruct]) -> list[tuple[AccountStruct | None, str]]:
    return [
        _attempt(lambda slot=slot: account_type.from_buffer_copy(registry.AccountData[slot]))
        for slot in range(min(len(registry.AccountData), _MAX_SLOTS))
    ]


def _publication(account: AccountStruct) -> tuple[object, ...]:
    data = account.AgentData
    return (
        account.IsAccount,
        account.IsSlotActive,
        _key(account),
        data.LoginNumber,
        account.LastUpdated,
        account.IsolationGroupID,
        account.IsIsolated,
        account.AgentPartyData.PartyID,
        (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language),
    )


def _collect(lines: list[str]) -> set[str] | None:
    # Never import or construct runtime owners: HeroAI imports register callbacks.
    cache = cast("GlobalCache | None", _loaded("Py4GWCoreLib.GlobalCache", "GLOBAL_CACHE"))
    if cache is None:
        lines.append("SERVICES registry=unavailable selection=unavailable reason=cache_not_loaded")
        return None
    account_type = cast(
        "type[AccountStruct] | None",
        _loaded("Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct", "AccountStruct"),
    )
    map_member = _loaded("Py4GWCoreLib.Map", "Map")
    player_member = _loaded("Py4GWCoreLib.Player", "Player")
    map_service = cast("type[Map]", map_member)
    player_service = cast("type[Player]", player_member)
    timeout_value = _loaded(
        "Py4GWCoreLib.GlobalCache.shared_memory_src.Globals", "SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS"
    )
    timeout = timeout_value if type(timeout_value) is int and timeout_value > 0 else None
    expected_slots = _loaded("Py4GWCoreLib.GlobalCache.shared_memory_src.Globals", "SHMEM_MAX_PLAYERS")
    email_value, email_error = _attempt(lambda: player_service.GetAccountEmail(), _PLAYER_DEPENDENCIES)
    own_email = email_value or ""
    own_location, location_error = _attempt(
        lambda: (
            map_service.GetMapID(),
            map_service.GetRegion()[0],
            map_service.GetDistrict(),
            map_service.GetLanguage()[0],
        ),
        _MAP_DEPENDENCIES,
    )
    live_party, party_error = _attempt(lambda: cache.Party.GetPartyID(), _PLAYER_DEPENDENCIES)
    readiness = {
        "map_ready": (lambda: map_service.IsMapReady(), _MAP_DEPENDENCIES),
        "map_loading": (lambda: map_service.IsMapLoading(), _MAP_DEPENDENCIES),
        "outpost": (lambda: map_service.IsOutpost(), _MAP_DEPENDENCIES),
        "player_loaded": (lambda: player_service.IsPlayerLoaded(), _PLAYER_DEPENDENCIES),
        "party_loaded": (lambda: cache.Party.IsPartyLoaded(), _PLAYER_DEPENDENCIES),
    }
    lines.append(
        f"LOCAL id={_token(own_email)} email_available={bool(own_email)} email_error={email_error} "
        f"map={own_location} map_error={location_error} live_party={live_party} party_error={party_error}"
    )
    for label, (read, dependencies) in readiness.items():
        value, error = _attempt(read, dependencies)
        lines.append(f"READY {label}={value} error={error}")
    handler = cast("WidgetHandler | None", _loaded("Py4GWCoreLib.py4gwcorelib_src.WidgetManager", "_widget_handler"))
    for name in ("HeroAI", "Messaging", "Environment Upkeeper"):
        enabled, error = (
            _attempt(lambda name=name: handler.is_widget_enabled(name))
            if handler is not None
            else (None, "manager_not_loaded")
        )
        lines.append(f"WIDGET name={name.replace(' ', '_')} enabled={enabled} error={error}")

    # GetAllAccounts retries attachment lazily. Observation must not initialize it.
    shmem = vars(cache).get("ShMem")
    shmem_state = cast("dict[str, object]", vars(shmem)) if shmem is not None else {}
    if shmem_state.get("shm") is None or account_type is None:
        lines.append("SERVICES registry=unavailable selection=unavailable reason=registry_not_attached_or_loaded")
        return None
    if _loaded("Py4GWCoreLib.py4gwcorelib_src.FrameCache", "FRAME_CACHE") is None:
        lines.append("SERVICES registry=unavailable selection=unavailable reason=registry_cache_unavailable")
        return None
    registry = cache.ShMem.GetAllAccounts()
    slot_count = len(registry.AccountData)
    first = _scan(registry, account_type)
    visible, visible_error = (
        _attempt(lambda: {_key(a) for a in cache.ShMem.GetAllAccountData()}, _PLAYER_DEPENDENCIES)
        if own_email
        else (None, "local_identity_unavailable")
    )
    api_type = _loaded("Py4GWCoreLib.HeroAI.command_api", "HeroAICommandAPI")
    api = cast("HeroAICommandAPI | None", vars(api_type).get("_instance") if isinstance(api_type, type) else None)
    selected, selected_error = (
        _attempt(
            lambda: {_key(a) for a in cast("Callable[[], list[AccountStruct]]", getattr(api, "_resolve_accounts"))()},
            _PLAYER_DEPENDENCIES,
        )
        if api is not None and own_email
        else (None, "service_or_instance_not_loaded")
    )
    # Read the loaded implementation's policy; do not substitute a permissive fallback.
    authorize = cast(Callable[[str, str], bool], getattr(registry, "_can_communicate", None))
    is_hidden = cast(Callable[[int], bool], getattr(registry, "_is_slot_isolated", None))
    lines.append(
        f"SELECTION visible_error={visible_error} selected_error={selected_error} "
        f"identity_guard_api={hasattr(type(registry), 'GetAuthorizedAccountSlot')}"
    )
    lines.append(
        "SCOPE ids=diagnostic_instance_only slots_reusable=True atomic_snapshot=False map_order=map,region,district,language"
    )

    rows: list[tuple[int, AccountStruct]] = []
    for slot, (account, error) in enumerate(first):
        if account is None:
            lines.append(f"ACCOUNT slot={slot} state=read_error error={error}")
        elif account.IsAccount:
            rows.append((slot, account))

    now, clock_error = _attempt(_clock)
    fresh_counts = Counter(
        a.AccountEmail
        for _, a in rows
        if a.AccountEmail
        and a.IsSlotActive
        and timeout is not None
        and (age := _age(now, int(a.LastUpdated))) is not None
        and age < timeout
    )
    own_slots = [slot for slot, a in rows if a.AccountEmail == own_email and own_email]
    current_tokens: set[str] = set()
    for slot, account in rows:
        email, data = account.AccountEmail, account.AgentData
        token = _token(email)
        if email:
            current_tokens.add(token)
        location = (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language)
        age = _age(now, int(account.LastUpdated))
        fresh = None if age is None or timeout is None else bool(account.IsSlotActive and age < timeout)
        key = _key(account)
        seen = None if visible is None else key in visible
        chosen = None if selected is None else key in selected
        hidden, hidden_error = (
            _attempt(lambda slot=slot: is_hidden(slot), _PLAYER_DEPENDENCIES)
            if own_email
            else (None, "local_identity_unavailable")
        )
        allowed, auth_error = (
            _attempt(lambda email=email: authorize(own_email, email), (("PySystem", "Console"),))
            if own_email
            else (None, "local_identity_unavailable")
        )
        identity_ready = bool(email and data.AgentID > 0 and data.LoginNumber > 0 and data.CharacterName)
        if not account.IsSlotActive:
            state = "inactive"
        elif age is None or timeout is None:
            state = "freshness_unknown"
        elif not fresh:
            state = "stale"
        elif not identity_ready or int(account.SlotNumber) != slot:
            state = "identity_unready"
        elif fresh_counts[email] > 1:
            state = "duplicate_live_identity"
        elif seen is None:
            state = "visibility_unknown"
        elif not seen:
            state = "hidden_isolation" if hidden is True else "hidden_other_or_changed"
        elif chosen is None:
            state = "selection_unavailable"
        elif not chosen:
            state = (
                "excluded_location" if own_location is not None and location != own_location else "selection_excluded"
            )
        else:
            state = (
                "selected"
                if allowed is True
                else "selected_authorization_denied" if allowed is False else "selected_authorization_unknown"
            )
        lines.append(
            f"ACCOUNT slot={slot} id={token} self={email == own_email if own_email else None} state={state} "
            f"active={account.IsSlotActive} age_ms={age} fresh={fresh} group={account.IsolationGroupID} "
            f"isolated={account.IsIsolated} party={account.AgentPartyData.PartyID} map={location} "
            f"agent={data.AgentID} login={data.LoginNumber} name_present={bool(data.CharacterName)} "
            f"live_rows={fresh_counts[email]} visible={seen} selected={chosen} "
            f"isolation_hidden={hidden}/{hidden_error} authorized={allowed}/{auth_error}"
        )
    confirm = _scan(registry, account_type)
    copy_errors = [slot for slot, (a, _) in enumerate(first) if a is None]
    confirm_errors = [slot for slot, (a, _) in enumerate(confirm) if a is None]
    changed = [
        slot
        for slot, ((a, _), (b, _)) in enumerate(zip(first, confirm))
        if a is not None and b is not None and _publication(a) != _publication(b)
    ]
    invalid = [
        slot
        for slot, (a, _) in enumerate(confirm)
        if a is not None and a.IsAccount and (not a.AccountEmail or int(a.SlotNumber) != slot)
    ]
    confirmed_email, confirm_error = _attempt(lambda: player_service.GetAccountEmail(), _PLAYER_DEPENDENCIES)
    identity_stable = bool(own_email) and confirmed_email == own_email and confirm_error == "none"
    scan_complete = (
        type(expected_slots) is int
        and expected_slots > 0
        and slot_count == expected_slots == len(registry.AccountData) == len(first) == len(confirm)
        and slot_count <= _MAX_SLOTS
        and not (copy_errors or confirm_errors or changed or invalid)
    )
    comparison_valid = scan_complete and identity_stable
    lines.append(
        f"REGISTRY account_rows={len(rows)} self_slots={own_slots} scan_complete={scan_complete} "
        f"identity_stable={identity_stable} clock_error={clock_error} timeout_ms={timeout} "
        f"self_missing={not bool(own_slots) if comparison_valid else None}"
    )
    lines.append(f"SCAN copy_errors={copy_errors} confirm_errors={confirm_errors}")
    lines.append(f"SCAN changed_slots={changed} invalid_slots={invalid}")
    if comparison_valid:
        missing = sorted(_previous_tokens - current_tokens)
        for start in range(0, len(missing), 16):
            lines.append(f"MISSING_SINCE_PREVIOUS ids={','.join(missing[start:start + 16])}")
    lines.append(
        "NOTE unseen_expected_accounts_cannot_be_inferred; selected_is_not_invited; authorization_failure_is_not_policy_proof"
    )
    return current_tokens if comparison_valid else None


def _capture_snapshot() -> None:
    global _capture_number, _secret, _previous_tokens, _baseline_number, _status

    _capture_number += 1
    lines = [f"BEGIN snapshot={_capture_number} baseline_snapshot={_baseline_number}"]
    current: set[str] | None = None
    try:
        if _secret is None:
            _secret = secrets.token_bytes(32)
        current = _collect(lines)
    except Exception as error:
        lines.append(f"ERROR stage=capture type={type(error).__name__[:48]}")
    if len(lines) >= _MAX_LINES or any(len(line) > _MAX_LINE_LENGTH for line in lines):
        current = None
        lines = lines[: _MAX_LINES - 2]
        lines.append("TRUNCATED comparison_baseline_not_eligible=True")
    lines.append(f"END snapshot={_capture_number} lines={len(lines) + 1}")
    try:
        console = _loaded("PySystem", "Console")
        message_type = _loaded("PySystem", "MessageType")
        log = cast("Callable[[str, str, PySystem.MessageType], None]", vars(console)["Log"])
        level = cast("PySystem.MessageType", vars(message_type)["Info"])
        for line in lines:
            log(MODULE_NAME, f"{_PREFIX} {line[:_MAX_LINE_LENGTH]}", level)
        if current is not None:
            _previous_tokens = current
            _baseline_number = _capture_number
        _status = f"Snapshot {_capture_number}: {len(lines)} console lines. Prefix: {_PREFIX}."
    except (Exception, KeyboardInterrupt):
        _status = "Console output failed. No automatic retry; press Capture Snapshot to retry."


def main() -> None:
    global _status

    try:
        visible = PyImGui.begin(
            MODULE_NAME, flags=PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoSavedSettings
        )
    except Exception:
        _status = "Unable to open the diagnostic window."
        return
    try:
        if visible:
            PyImGui.text("Passive account evidence; no invitations, travel, or settings changes.")
            if PyImGui.button("Capture Snapshot"):
                _capture_snapshot()
            PyImGui.text_wrapped(_status)
    except Exception:
        _status = "Diagnostic UI error. No background capture or console retry."
    finally:
        try:
            PyImGui.end()
        except Exception:
            _status = "Diagnostic window cleanup failed."
