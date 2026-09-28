import zlib
from collections.abc import Callable

import PySystem

from ..GlobalCache import GLOBAL_CACHE
from ..GlobalCache.WhiteboardLocks import clear_account_isolation_policy
from ..GlobalCache.WhiteboardLocks import publish_account_isolation_policy
from ..GlobalCache.WhiteboardLocks import read_account_isolation_policies
from ..Player import Player
from ..py4gwcorelib_src.BehaviorTree import BehaviorTree
from ..py4gwcorelib_src.Timer import ThrottledTimer

_ISOLATION_GROUPS_SETTINGS = 'Py4GW/IsolationGroups.ini'
# Match the existing short runtime throttles while preventing one setter attempt per HeroAI frame.
_ACCOUNT_ISOLATION_RETRY_INTERVAL_MS = 250
_ACTIVE_ACCOUNT_POLICIES: dict[str, tuple[int, bool]] = {}


def _normalized_email(account_email: str | None) -> str:
    return str(account_email or '').strip()


def _get_persisted_group_assignment(account_email: str) -> int | None:
    """Read a current Isolation Manager group assignment, if one exists."""
    try:
        from ..py4gwcorelib_src.Settings import Settings

        settings = Settings(_ISOLATION_GROUPS_SETTINGS, 'global')
        if not settings.has('Assignments', account_email):
            return None
        assignment = int(settings.get_int('Assignments', account_email, 0))
        if assignment <= 0:
            return 0

        group_count = int(settings.get_int('Groups', 'count', 0))
        for index in range(max(0, group_count)):
            if int(settings.get_int('Groups', f'id_{index}', 0)) != assignment:
                continue
            if str(settings.get_str('Groups', f'name_{index}', '') or '').strip():
                return assignment
        return None
    except Exception:
        return None


def _is_local_account(account_email: str) -> bool:
    try:
        return _normalized_email(Player.GetAccountEmail()) == _normalized_email(account_email)
    except Exception:
        return False


def _publish_local_account_isolation_policy(account_email: str, enabled: bool, *, force: bool = False) -> bool:
    if not _is_local_account(account_email):
        return False
    return bool(publish_account_isolation_policy(bool(enabled), force=force))


def set_active_account_isolation_policy(account_email: str, enabled: bool, owner: object) -> bool:
    """Register and publish the active BottingTree policy for its local account."""
    email = _normalized_email(account_email)
    if email:
        policy = (id(owner), bool(enabled))
        policy_changed = _ACTIVE_ACCOUNT_POLICIES.get(email) != policy
        _ACTIVE_ACCOUNT_POLICIES[email] = policy
        return _publish_local_account_isolation_policy(email, policy[1], force=policy_changed)
    return False


def clear_active_account_isolation_policy(account_email: str, owner: object) -> None:
    email = _normalized_email(account_email)
    policy = _ACTIVE_ACCOUNT_POLICIES.get(email)
    if policy is not None and policy[0] == id(owner):
        _ACTIVE_ACCOUNT_POLICIES.pop(email, None)
        if _is_local_account(email):
            clear_account_isolation_policy()


def resolve_account_isolation_enabled(
    account_email: str,
    *,
    requested_enabled: bool | None = None,
    default_enabled: bool = True,
    owner: object | None = None,
) -> bool:
    """Resolve the one per-account isolation policy used by all consumers.

    An active BottingTree's effective policy is authoritative. Isolation Manager assignments only
    select a group; group zero means ungrouped and never decides enabled/disabled participation.
    Without an active owner, standalone HeroAI uses its established default.
    """
    email = _normalized_email(account_email)
    active_policy = _ACTIVE_ACCOUNT_POLICIES.get(email)
    if active_policy is not None and (owner is None or active_policy[0] != id(owner)):
        return bool(active_policy[1])

    if requested_enabled is not None:
        return bool(requested_enabled)

    return bool(default_enabled)


def _is_account_isolation_eligible(account, policies: dict[str, bool]) -> bool:
    """Return whether a party peer has opted into isolation-group participation."""
    email = _normalized_email(getattr(account, 'AccountEmail', ''))
    if not email:
        return False
    published_policy = policies.get(email)
    if published_policy is not None:
        return bool(published_policy)

    active_policy = _ACTIVE_ACCOUNT_POLICIES.get(email)
    if active_policy is not None:
        return bool(active_policy[1])

    persisted_group_id = _get_persisted_group_assignment(email)
    if persisted_group_id is not None and persisted_group_id > 0:
        return True

    # The Manager exposes this separately from the persisted group assignment. It is only a
    # compatibility fallback for accounts that have not yet published an explicit heartbeat.
    return bool(getattr(account, 'IsIsolated', False))


def _get_account_data(account_email: str):
    return GLOBAL_CACHE.ShMem.GetAccountDataFromEmail(account_email)


def _get_party_members(account_email: str):
    local_account = _get_account_data(account_email)
    if local_account is None:
        return None

    party_id = int(getattr(getattr(local_account, 'AgentPartyData', None), 'PartyID', 0) or 0)
    if party_id <= 0:
        return 0, ()

    try:
        accounts = (
            GLOBAL_CACHE.ShMem.GetAllAccountData(
                sort_results=False,
                include_isolated=True,
            )
            or ()
        )
    except Exception:
        return None

    members = []
    for account in accounts:
        if not bool(getattr(account, 'IsAccount', False)):
            continue
        email = _normalized_email(getattr(account, 'AccountEmail', ''))
        candidate_party_id = int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0)
        if email and candidate_party_id == party_id:
            members.append(account)
    return party_id, tuple(members)


def resolve_isolation_group_id(account_email: str) -> int:
    account_email = _normalized_email(account_email)
    account = _get_account_data(account_email)
    existing_group_id = int(getattr(account, 'IsolationGroupID', 0) or 0) if account else 0
    persisted_group_id = _get_persisted_group_assignment(account_email)
    party_members = _get_party_members(account_email)

    if party_members is not None:
        party_id, members = party_members
        if party_id > 0:
            policies = read_account_isolation_policies()
            eligible_members = [
                member for member in members if _is_account_isolation_eligible(member, policies)
            ]
            # Eligible clients see the same isolated rows and choose the same established positive
            # assignment. If none exists, the live party id is the deterministic party scope.
            positive_groups = {
                int(getattr(member, 'IsolationGroupID', 0) or 0)
                for member in eligible_members
                if int(getattr(member, 'IsolationGroupID', 0) or 0) > 0
            }
            for member in eligible_members:
                member_email = _normalized_email(getattr(member, 'AccountEmail', ''))
                member_assignment = _get_persisted_group_assignment(member_email)
                if member_assignment is not None and member_assignment > 0:
                    positive_groups.add(member_assignment)
            if positive_groups:
                return min(positive_groups)
            return party_id

    if persisted_group_id is not None and persisted_group_id > 0:
        return persisted_group_id
    if existing_group_id > 0:
        return existing_group_id

    deterministic_group = int(zlib.crc32(account_email.encode('utf-8')) % 1_000_000)
    return max(1, deterministic_group)


def sync_party_isolation_group(account_email: str, group_id: int) -> bool:
    party_members = _get_party_members(account_email)
    if party_members is None:
        return False

    local_party_id, members = party_members
    if local_party_id <= 0:
        return False

    changed = False
    policies = read_account_isolation_policies()
    for account in members:
        other_email = _normalized_email(getattr(account, 'AccountEmail', ''))
        if not other_email:
            continue
        if other_email != account_email and not _is_account_isolation_eligible(account, policies):
            continue

        other_group_id = int(getattr(account, 'IsolationGroupID', 0) or 0)
        if other_group_id != group_id:
            changed = bool(GLOBAL_CACHE.ShMem.SetAccountGroupByEmail(other_email, group_id)) or changed

        if not bool(getattr(account, 'IsIsolated', False)):
            changed = bool(GLOBAL_CACHE.ShMem.SetAccountIsolationByEmail(other_email, True)) or changed

    return changed


def apply_account_isolation(
    account_email: str,
    isolation_enabled: bool | None = None,
    *,
    sync_party_isolation: bool = True,
    group_resolver: Callable[[str], int] | None = None,
    publish_policy: bool = True,
) -> bool:
    account_email = _normalized_email(account_email)
    if not account_email:
        return False

    enabled = resolve_account_isolation_enabled(
        account_email,
        requested_enabled=isolation_enabled,
    )
    if publish_policy and not _publish_local_account_isolation_policy(account_email, enabled):
        return False
    changed = False
    current_isolated = bool(GLOBAL_CACHE.ShMem.IsAccountIsolated(account_email))
    if current_isolated != enabled:
        changed = bool(GLOBAL_CACHE.ShMem.SetAccountIsolationByEmail(account_email, enabled)) or changed

    if enabled:
        resolver = group_resolver or resolve_isolation_group_id
        target_group_id = int(resolver(account_email))
        current_group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(account_email) or 0)
        if current_group_id != target_group_id:
            changed = bool(GLOBAL_CACHE.ShMem.SetAccountGroupByEmail(account_email, target_group_id)) or changed
        if sync_party_isolation:
            changed = sync_party_isolation_group(account_email, target_group_id) or changed
    else:
        current_group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(account_email) or 0)
        if current_group_id != 0:
            changed = bool(GLOBAL_CACHE.ShMem.SetAccountGroupByEmail(account_email, 0)) or changed

    return bool(changed)


class AccountIsolationBootstrap:
    """Retryable, idempotent account-isolation initialization for widget lifecycles."""

    def __init__(
        self,
        *,
        isolation_enabled: bool | None = None,
        sync_party_isolation: bool = True,
        retry_interval_ms: int = _ACCOUNT_ISOLATION_RETRY_INTERVAL_MS,
        retry_timer=None,
    ):
        self.isolation_enabled = isolation_enabled
        self.sync_party_isolation = bool(sync_party_isolation)
        self._retry_timer = retry_timer or ThrottledTimer(retry_interval_ms)
        self._last_context: tuple[object, ...] | None = None
        self._last_attempt_key: tuple[object, ...] | None = None
        self._retry_ready = True
        self._retry_failures = 0

    def reset(self) -> None:
        self._last_context = None
        self._last_attempt_key = None
        self._retry_ready = True
        self._retry_failures = 0

    def set_isolation_enabled(self, enabled: bool | None) -> None:
        enabled = bool(enabled) if enabled is not None else None
        if self.isolation_enabled != enabled:
            self.isolation_enabled = enabled
            self.reset()

    def _party_signature(self, account_email: str) -> tuple[int, tuple[tuple[str, bool, int, bool], ...]] | None:
        if not self.sync_party_isolation:
            return None

        party_members = _get_party_members(account_email)
        if party_members is None:
            return None
        party_id, members = party_members
        if party_id <= 0:
            return (0, ())

        policies = read_account_isolation_policies()
        return party_id, tuple(
            sorted(
                (
                    _normalized_email(getattr(account, 'AccountEmail', '')),
                    _is_account_isolation_eligible(account, policies),
                    int(getattr(account, 'IsolationGroupID', 0) or 0),
                    bool(getattr(account, 'IsIsolated', False)),
                )
                for account in members
            )
        )

    def _record_retry_failure(self, reason: str) -> None:
        self._last_context = None
        self._retry_ready = False
        self._retry_timer.Reset()
        self._retry_failures += 1
        if self._retry_failures not in (1, 3, 10):
            return
        try:
            try:
                message_type = PySystem.Console.MessageType.Warning
            except AttributeError:
                message_type = PySystem.Console.MessageType.Info
            PySystem.Console.Log(
                'HeroAI',
                f'Account isolation bootstrap retry pending: {reason}.',
                message_type,
            )
        except Exception:
            pass

    def _retry_is_due(self, attempt_key: tuple[object, ...]) -> bool:
        if attempt_key != self._last_attempt_key:
            self._last_attempt_key = attempt_key
            self._retry_ready = True
            self._retry_failures = 0
        if self._retry_ready:
            return True
        try:
            return bool(self._retry_timer.IsExpired())
        except Exception:
            return True

    def _context_is_valid(
        self,
        account,
        enabled: bool,
        party_signature: tuple[int, tuple[tuple[str, bool, int, bool], ...]] | None,
    ) -> bool:
        group_id = int(getattr(account, 'IsolationGroupID', 0) or 0)
        isolated = bool(getattr(account, 'IsIsolated', False))
        if enabled:
            if group_id <= 0 or not isolated:
                return False
            if self.sync_party_isolation:
                party_id = int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0)
                if party_id > 0:
                    if party_signature is None or party_signature[0] != party_id:
                        return False
                    members = [member for member in party_signature[1] if member[1]]
                    if not members or not all(
                        member_group_id == group_id and member_isolated
                        for _, _, member_group_id, member_isolated in members
                    ):
                        return False
            return True
        return group_id == 0 and not isolated

    def ensure(self, account_email: str | None = None) -> bool:
        email = _normalized_email(account_email if account_email is not None else Player.GetAccountEmail())
        if not email:
            self.reset()
            return False

        try:
            account = _get_account_data(email)
        except Exception:
            self.reset()
            return False

        if account is None or not bool(getattr(account, 'IsAccount', False)):
            self._last_context = None
            self._retry_ready = True
            return False

        enabled = resolve_account_isolation_enabled(
            email,
            requested_enabled=self.isolation_enabled,
        )
        if not _publish_local_account_isolation_policy(email, enabled):
            self._record_retry_failure('policy_publish_failed')
            return False
        party_signature = self._party_signature(email)
        current_context = (
            email,
            enabled,
            int(getattr(account, 'IsolationGroupID', 0) or 0),
            bool(getattr(account, 'IsIsolated', False)),
            party_signature,
        )
        if self._context_is_valid(account, enabled, party_signature):
            self._last_context = current_context
            self._retry_ready = True
            self._retry_failures = 0
            return True

        attempt_key = (email, enabled, party_signature)
        if not self._retry_is_due(attempt_key):
            return False

        try:
            apply_account_isolation(
                email,
                enabled,
                sync_party_isolation=self.sync_party_isolation,
                publish_policy=False,
            )
        except Exception:
            self._record_retry_failure('apply_failed')
            return False

        try:
            account = _get_account_data(email)
            if account is None or not bool(getattr(account, 'IsAccount', False)):
                self._record_retry_failure('account_context_missing')
                return False
            party_signature = self._party_signature(email)
        except Exception:
            self._record_retry_failure('owner_context_lookup_failed')
            return False

        current_context = (
            email,
            enabled,
            int(getattr(account, 'IsolationGroupID', 0) or 0),
            bool(getattr(account, 'IsIsolated', False)),
            party_signature,
        )
        if not self._context_is_valid(account, enabled, party_signature):
            self._record_retry_failure('context_not_ready')
            return False

        self._last_context = current_context
        self._retry_ready = True
        self._retry_failures = 0
        return True


class BottingTreeIsolationMixin:
    def _resolve_isolation_group_id(self, account_email: str) -> int:
        return resolve_isolation_group_id(account_email)

    def SetAccountConfig(self, config) -> None:
        from .account_config import BottingTreeAccountConfig

        self.account_config = BottingTreeAccountConfig.coerce(config)
        self.isolation_enabled = self.account_config.resolve_isolation_enabled()

    def GetAccountConfig(self):
        return self.account_config

    def SetAccountMode(self, mode, *, apply_runtime: bool = True) -> bool:
        from .account_config import BottingTreeAccountMode

        self.account_config.mode = BottingTreeAccountMode.coerce(mode)
        if self.account_config.isolation_enabled is None:
            self.isolation_enabled = self.account_config.resolve_isolation_enabled()
        if apply_runtime:
            return self.ApplyAccountIsolation()
        return False

    def SetMultiAccount(self, multi_account: bool, *, apply_runtime: bool = True) -> bool:
        from .account_config import BottingTreeAccountMode

        self.account_config.mode = (
            BottingTreeAccountMode.MULTI_ACCOUNT if multi_account else BottingTreeAccountMode.SINGLE_ACCOUNT
        )
        if self.account_config.isolation_enabled is None:
            self.isolation_enabled = self.account_config.resolve_isolation_enabled()
        if apply_runtime:
            return self.ApplyAccountIsolation()
        return False

    def GetAccountMode(self) -> str:
        return self.account_config.mode.value

    def IsSingleAccountMode(self) -> bool:
        return self.GetAccountMode() == 'single_account'

    def IsMultiAccountMode(self) -> bool:
        return self.GetAccountMode() == 'multi_account'

    def _sync_party_isolation_group(self, account_email: str, group_id: int) -> bool:
        return sync_party_isolation_group(account_email, group_id)

    def RefreshAccountIsolationPolicy(self) -> bool:
        if not bool(getattr(self, 'started', False)):
            return False
        account_email = Player.GetAccountEmail()
        if not account_email:
            return False
        effective_enabled = self.account_config.resolve_isolation_enabled()
        self.isolation_enabled = effective_enabled
        published = set_active_account_isolation_policy(account_email, effective_enabled, self)
        if published and bool(getattr(self, '_account_isolation_apply_pending', False)):
            self._account_isolation_apply_pending = False
            self.ApplyAccountIsolation()
        return published

    def _capture_isolation_state_for_restore(self) -> None:
        account_email = Player.GetAccountEmail()
        if not account_email:
            self._previous_isolation_state = None
            self._previous_isolation_group_id = None
            return
        self._previous_isolation_state = bool(GLOBAL_CACHE.ShMem.IsAccountIsolated(account_email))
        self._previous_isolation_group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(account_email) or 0)

    def ApplyAccountIsolation(self) -> bool:
        account_email = Player.GetAccountEmail()
        if not account_email:
            return False

        effective_enabled = self.account_config.resolve_isolation_enabled()
        self.isolation_enabled = effective_enabled
        if not set_active_account_isolation_policy(account_email, effective_enabled, self):
            self._account_isolation_apply_pending = True
            return False
        self._account_isolation_apply_pending = False
        changed = apply_account_isolation(
            account_email,
            effective_enabled,
            sync_party_isolation=bool(getattr(self.account_config, 'sync_party_isolation', True)),
            group_resolver=self._resolve_isolation_group_id,
            publish_policy=False,
        )

        if changed:
            PySystem.Console.Log(
                'BottingTree',
                f"Account isolation {'enabled' if self.isolation_enabled else 'disabled'} for {account_email}.",
                PySystem.Console.MessageType.Info,
            )
        return bool(changed)

    def RestoreAccountIsolation(self) -> bool:
        account_email = Player.GetAccountEmail()
        if not account_email:
            return False
        if not self.restore_isolation_on_stop:
            clear_active_account_isolation_policy(account_email, self)
            return False
        if self._previous_isolation_state is None:
            clear_active_account_isolation_policy(account_email, self)
            return False

        changed = False
        current_isolated = bool(GLOBAL_CACHE.ShMem.IsAccountIsolated(account_email))
        if current_isolated != bool(self._previous_isolation_state):
            changed = (
                bool(
                    GLOBAL_CACHE.ShMem.SetAccountIsolationByEmail(
                        account_email,
                        self._previous_isolation_state,
                    )
                )
                or changed
            )

        restore_group_id = int(self._previous_isolation_group_id or 0)
        current_group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(account_email) or 0)
        if current_group_id != restore_group_id:
            changed = bool(GLOBAL_CACHE.ShMem.SetAccountGroupByEmail(account_email, restore_group_id)) or changed

        if changed:
            PySystem.Console.Log(
                'BottingTree',
                f"Account isolation restored to {'enabled' if self._previous_isolation_state else 'disabled'} for {account_email}.",
                PySystem.Console.MessageType.Info,
            )
        self._previous_isolation_state = None
        self._previous_isolation_group_id = None
        clear_active_account_isolation_policy(account_email, self)
        return bool(changed)

    def SetIsolationEnabled(self, enabled: bool) -> bool:
        self.account_config.isolation_enabled = bool(enabled)
        self.isolation_enabled = enabled
        return self.ApplyAccountIsolation()

    def EnableIsolation(self) -> bool:
        return self.SetIsolationEnabled(True)

    def DisableIsolation(self) -> bool:
        return self.SetIsolationEnabled(False)

    def ToggleIsolation(self) -> bool:
        self.account_config.isolation_enabled = not self.isolation_enabled
        self.isolation_enabled = not self.isolation_enabled
        self.ApplyAccountIsolation()
        return self.isolation_enabled

    def IsIsolationEnabled(self) -> bool:
        return self.isolation_enabled

    def SetRestoreIsolationOnStop(self, enabled: bool) -> None:
        self.restore_isolation_on_stop = enabled

    @staticmethod
    def GetIsolationSetEnabledTree(
        enabled: bool,
        name: str | None = None,
    ) -> BehaviorTree:
        node_name = name or ('EnableIsolation' if enabled else 'DisableIsolation')

        def _request_toggle(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
            node.blackboard['account_isolation_enabled_request'] = enabled
            return BehaviorTree.NodeState.SUCCESS

        return BehaviorTree(
            BehaviorTree.ActionNode(
                name=node_name,
                action_fn=_request_toggle,
                aftercast_ms=0,
            )
        )

    @staticmethod
    def EnableIsolationTree() -> BehaviorTree:
        return BottingTreeIsolationMixin.GetIsolationSetEnabledTree(
            True,
            name='EnableIsolation',
        )

    @staticmethod
    def DisableIsolationTree() -> BehaviorTree:
        return BottingTreeIsolationMixin.GetIsolationSetEnabledTree(
            False,
            name='DisableIsolation',
        )

    @staticmethod
    def ToggleIsolationTree() -> BehaviorTree:
        def _request_toggle(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
            current_enabled = bool(node.blackboard.get('account_isolation_enabled', True))
            node.blackboard['account_isolation_enabled_request'] = not current_enabled
            return BehaviorTree.NodeState.SUCCESS

        return BehaviorTree(
            BehaviorTree.ActionNode(
                name='ToggleIsolation',
                action_fn=_request_toggle,
                aftercast_ms=0,
            )
        )
