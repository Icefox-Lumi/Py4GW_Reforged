"""Offline coverage for the shared HeroAI account-isolation bootstrap."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
ISOLATION_PATH = ROOT / "Py4GWCoreLib" / "botting_tree_src" / "isolation.py"


class _Account:
    def __init__(
        self,
        email: str,
        *,
        group_id: int = 0,
        party_id: int = 0,
        isolated: bool = False,
    ) -> None:
        self.AccountEmail = email
        self.IsAccount = True
        self.IsolationGroupID = group_id
        self.IsIsolated = isolated
        self.AgentPartyData = types.SimpleNamespace(PartyID=party_id)


class _SharedMemory:
    def __init__(self, accounts: list[_Account], owner_email: str) -> None:
        self.accounts = accounts
        self.owner_email = owner_email
        self.group_writes: list[tuple[str, int]] = []
        self.isolation_writes: list[tuple[str, bool]] = []
        self.group_attempts: list[tuple[str, int]] = []
        self.include_isolated_calls: list[bool] = []
        self.group_failures_remaining = 0

    def _find_account(self, email: str) -> _Account | None:
        return next(
            (account for account in self.accounts if account.IsAccount and account.AccountEmail == email),
            None,
        )

    def GetAccountDataFromEmail(self, email: str) -> _Account | None:
        account = self._find_account(email)
        if account is None or email == self.owner_email:
            return account

        owner = self._find_account(self.owner_email)
        owner_group = int(owner.IsolationGroupID) if owner else 0
        account_group = int(account.IsolationGroupID)
        if owner_group > 0:
            return account if account_group == owner_group else None
        return account if account_group == 0 else None

    def GetAllAccountData(
        self,
        *,
        sort_results: bool = True,
        include_isolated: bool = False,
    ) -> list[_Account]:
        del sort_results
        self.include_isolated_calls.append(bool(include_isolated))
        if include_isolated:
            return list(self.accounts)
        return [account for account in self.accounts if self.GetAccountDataFromEmail(account.AccountEmail) is not None]

    def IsAccountIsolated(self, email: str) -> bool:
        account = self._find_account(email)
        return bool(account and account.IsIsolated)

    def SetAccountIsolationByEmail(self, email: str, isolated: bool) -> bool:
        account = self._find_account(email)
        if account is None:
            return False
        value = bool(isolated)
        account.IsIsolated = value
        self.isolation_writes.append((email, value))
        return True

    def SetAccountGroupByEmail(self, email: str, group_id: int) -> bool:
        value = int(group_id)
        self.group_attempts.append((email, value))
        if self.group_failures_remaining > 0:
            self.group_failures_remaining -= 1
            return False
        account = self._find_account(email)
        if account is None:
            return False
        account.IsolationGroupID = value
        self.group_writes.append((email, value))
        return True

    def GetAccountGroupByEmail(self, email: str) -> int:
        account = self._find_account(email)
        return int(account.IsolationGroupID) if account else 0


class _Runtime:
    def __init__(self, accounts: list[_Account]) -> None:
        self.owner_email = "me@example.com"
        self.shared_memory = _SharedMemory(accounts, self.owner_email)
        self.isolation_policies: dict[str, bool] = {}
        self.console_logs: list[tuple[str, str, object]] = []


class _Settings:
    assignments: dict[str, int] = {}
    groups: dict[int, str] = {}

    def __init__(self, _name: str, _scope: str = 'account') -> None:
        pass

    def has(self, section: str, key: str) -> bool:
        return section == 'Assignments' and key in self.assignments

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        if section == 'Assignments':
            return int(self.assignments.get(key, default))
        if section != 'Groups':
            return default
        group_ids = sorted(self.groups)
        if key == 'count':
            return len(group_ids)
        if key.startswith('id_'):
            try:
                return int(group_ids[int(key.removeprefix('id_'))])
            except (IndexError, ValueError):
                return default
        return default

    def get_str(self, section: str, key: str, default: str = '') -> str:
        if section != 'Groups' or not key.startswith('name_'):
            return default
        try:
            group_id = sorted(self.groups)[int(key.removeprefix('name_'))]
        except (IndexError, ValueError):
            return default
        return self.groups.get(group_id, default)


class _RetryTimer:
    def __init__(self) -> None:
        self.expired = False
        self.reset_count = 0

    def IsExpired(self) -> bool:
        return self.expired

    def Reset(self) -> None:
        self.expired = False
        self.reset_count += 1


def _install_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _loaded_isolation(accounts: list[_Account]) -> Iterator[tuple[Any, _Runtime]]:
    prefixes = ("Py4GWCoreLib", "PySystem")
    original = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
    }
    runtime = _Runtime(accounts)
    _Settings.assignments = {}
    _Settings.groups = {}
    try:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)

        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.GlobalCache", ROOT / "Py4GWCoreLib" / "GlobalCache")
        _install_package("Py4GWCoreLib.botting_tree_src", ROOT / "Py4GWCoreLib" / "botting_tree_src")
        _install_package("Py4GWCoreLib.py4gwcorelib_src", ROOT / "Py4GWCoreLib" / "py4gwcorelib_src")

        global_cache = types.ModuleType("Py4GWCoreLib.GlobalCache")
        setattr(global_cache, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=runtime.shared_memory))
        sys.modules[global_cache.__name__] = global_cache

        player_module = types.ModuleType("Py4GWCoreLib.Player")
        setattr(player_module, "Player", types.SimpleNamespace(GetAccountEmail=lambda: runtime.owner_email))
        sys.modules[player_module.__name__] = player_module

        isolation_policy_module = types.ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")

        def _publish_isolation_policy(enabled: bool, *, force: bool = False) -> bool:
            del force
            runtime.isolation_policies[runtime.owner_email] = bool(enabled)
            return True

        def _clear_isolation_policy() -> bool:
            runtime.isolation_policies.pop(runtime.owner_email, None)
            return True

        setattr(isolation_policy_module, "publish_account_isolation_policy", _publish_isolation_policy)
        setattr(isolation_policy_module, "clear_account_isolation_policy", _clear_isolation_policy)
        setattr(isolation_policy_module, "read_account_isolation_policies", lambda: dict(runtime.isolation_policies))
        sys.modules[isolation_policy_module.__name__] = isolation_policy_module

        behavior_tree = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.BehaviorTree")
        setattr(behavior_tree, "BehaviorTree", type("BehaviorTree", (), {}))
        sys.modules[behavior_tree.__name__] = behavior_tree

        settings_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.Settings")
        setattr(settings_module, "Settings", _Settings)
        sys.modules[settings_module.__name__] = settings_module

        console_logs: list[tuple[str, str, object]] = []
        runtime.console_logs = console_logs
        py_system = types.ModuleType("PySystem")
        setattr(
            py_system,
            "Console",
            types.SimpleNamespace(
                MessageType=types.SimpleNamespace(Info=0, Warning=1),
                Log=lambda source, message, level: console_logs.append((source, message, level)),
            ),
        )
        sys.modules[py_system.__name__] = py_system

        module = _load_module("Py4GWCoreLib.botting_tree_src.isolation", ISOLATION_PATH)
        yield module, runtime
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)
        sys.modules.update(original)


def test_enabled_standalone_bootstraps_zero_group_to_canonical_positive_group() -> None:
    account = _Account("me@example.com")
    with _loaded_isolation([account]) as (module, runtime):
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == module.resolve_isolation_group_id(account.AccountEmail)
        assert account.IsolationGroupID > 0
        assert account.IsIsolated is True
        assert runtime.isolation_policies == {account.AccountEmail: True}
        assert runtime.shared_memory.group_writes == [(account.AccountEmail, account.IsolationGroupID)]


def test_existing_positive_group_is_preserved_and_bootstrap_is_idempotent() -> None:
    account = _Account("me@example.com", group_id=77, isolated=True)
    with _loaded_isolation([account]) as (module, runtime):
        bootstrap = module.AccountIsolationBootstrap(isolation_enabled=True)

        assert bootstrap.ensure() is True
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 77
        assert runtime.shared_memory.group_writes == []
        assert runtime.shared_memory.isolation_writes == []


def test_explicitly_disabled_isolation_keeps_group_zero() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    with _loaded_isolation([account]) as (module, runtime):
        bootstrap = module.AccountIsolationBootstrap(isolation_enabled=False)

        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 0
        assert account.IsIsolated is False
        assert runtime.shared_memory.group_writes == []


def test_persisted_zero_assignment_means_ungrouped_not_disabled() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    with _loaded_isolation([account]) as (module, runtime):
        _Settings.assignments[account.AccountEmail] = 0
        bootstrap = module.AccountIsolationBootstrap()

        assert module.resolve_account_isolation_enabled(account.AccountEmail) is True
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID > 0
        assert account.IsIsolated is True


def test_persisted_positive_assignment_is_consumed_by_bootstrap() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    with _loaded_isolation([account]) as (module, runtime):
        _Settings.assignments[account.AccountEmail] = 123
        _Settings.groups[123] = 'Configured group'
        bootstrap = module.AccountIsolationBootstrap()

        assert module.resolve_account_isolation_enabled(account.AccountEmail) is True
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 123
        assert runtime.shared_memory.group_writes == [(account.AccountEmail, 123)]


def test_stale_manager_assignment_falls_back_without_becoming_a_policy_or_group() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    with _loaded_isolation([account]) as (module, runtime):
        _Settings.assignments[account.AccountEmail] = 999
        bootstrap = module.AccountIsolationBootstrap()

        assert module._get_persisted_group_assignment(account.AccountEmail) is None
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID > 0
        assert account.IsolationGroupID != 999
        assert account.IsIsolated is True


def test_active_botting_tree_policy_overrides_standalone_default() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    owner = object()
    with _loaded_isolation([account]) as (module, runtime):
        module.set_active_account_isolation_policy(account.AccountEmail, False, owner)
        bootstrap = module.AccountIsolationBootstrap()

        assert module.resolve_account_isolation_enabled(account.AccountEmail) is False
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 0
        assert runtime.shared_memory.group_writes == []

        module.clear_active_account_isolation_policy(account.AccountEmail, owner)


def test_row_not_ready_does_not_fabricate_state_and_retries_later() -> None:
    account = _Account("me@example.com")
    with _loaded_isolation([]) as (module, runtime):
        bootstrap = module.AccountIsolationBootstrap(isolation_enabled=True)

        assert bootstrap.ensure() is False
        assert runtime.shared_memory.group_writes == []

        runtime.shared_memory.accounts.append(account)
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID > 0


def test_party_membership_changes_reuse_the_same_canonical_group() -> None:
    account = _Account("me@example.com", party_id=42)
    party_member = _Account("party@example.com", party_id=42)
    unrelated = _Account("other@example.com", party_id=99)
    with _loaded_isolation([account, party_member, unrelated]) as (module, runtime):
        runtime.isolation_policies[party_member.AccountEmail] = True
        bootstrap = module.AccountIsolationBootstrap(isolation_enabled=True)

        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 42
        assert party_member.IsolationGroupID == 42
        assert unrelated.IsolationGroupID == 0

        new_member = _Account("new-party@example.com", party_id=42)
        runtime.shared_memory.accounts.append(new_member)
        runtime.isolation_policies[new_member.AccountEmail] = True
        assert bootstrap.ensure() is True
        assert new_member.IsolationGroupID == 42


def test_same_party_mismatched_positive_groups_converge_using_visible_isolated_rows() -> None:
    account = _Account("me@example.com", group_id=101, party_id=42, isolated=True)
    party_member = _Account("party@example.com", group_id=202, party_id=42, isolated=True)
    with _loaded_isolation([account, party_member]) as (module, runtime):
        runtime.isolation_policies[account.AccountEmail] = True
        runtime.isolation_policies[party_member.AccountEmail] = True
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 101
        assert party_member.IsolationGroupID == 101
        assert True in runtime.shared_memory.include_isolated_calls
        assert runtime.shared_memory.group_writes == [(party_member.AccountEmail, 101)]


def test_same_party_positive_and_zero_group_converge_to_existing_positive_group() -> None:
    account = _Account("me@example.com", group_id=77, party_id=42, isolated=True)
    party_member = _Account("party@example.com", group_id=0, party_id=42, isolated=False)
    with _loaded_isolation([account, party_member]) as (module, runtime):
        runtime.isolation_policies[account.AccountEmail] = True
        runtime.isolation_policies[party_member.AccountEmail] = True
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is True
        assert account.IsolationGroupID == 77
        assert party_member.IsolationGroupID == 77
        assert party_member.IsIsolated is True


def test_same_party_disabled_peer_is_not_reenabled_or_reassigned_across_frames() -> None:
    account = _Account("me@example.com", group_id=101, party_id=42, isolated=True)
    party_member = _Account("party@example.com", group_id=0, party_id=42, isolated=False)
    with _loaded_isolation([account, party_member]) as (module, runtime):
        runtime.isolation_policies[account.AccountEmail] = True
        runtime.isolation_policies[party_member.AccountEmail] = False
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is True
        assert bootstrap.ensure() is True
        assert party_member.IsolationGroupID == 0
        assert party_member.IsIsolated is False
        assert runtime.shared_memory.group_writes == []
        assert runtime.shared_memory.isolation_writes == []


def test_party_leave_stops_reconciling_the_former_party_member() -> None:
    account = _Account("me@example.com", group_id=0, party_id=42)
    party_member = _Account("party@example.com", group_id=0, party_id=42)
    with _loaded_isolation([account, party_member]) as (module, runtime):
        runtime.isolation_policies[party_member.AccountEmail] = True
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is True
        writes_before_leave = list(runtime.shared_memory.group_writes)
        party_member.AgentPartyData.PartyID = 99
        party_member.IsolationGroupID = 0
        party_member.IsIsolated = False

        assert bootstrap.ensure() is True
        assert runtime.shared_memory.group_writes == writes_before_leave
        assert party_member.IsolationGroupID == 0


def test_failed_group_write_is_throttled_then_recovers() -> None:
    account = _Account("me@example.com")
    retry_timer = _RetryTimer()
    with _loaded_isolation([account]) as (module, runtime):
        runtime.shared_memory.group_failures_remaining = 1
        bootstrap = module.AccountIsolationBootstrap(retry_timer=retry_timer)

        assert bootstrap.ensure() is False
        assert len(runtime.shared_memory.group_attempts) == 1
        assert len(runtime.console_logs) == 1
        for _ in range(4):
            assert bootstrap.ensure() is False
        assert len(runtime.shared_memory.group_attempts) == 1
        assert len(runtime.console_logs) == 1
        assert retry_timer.reset_count == 1

        retry_timer.expired = True
        assert bootstrap.ensure() is True
        assert len(runtime.shared_memory.group_attempts) == 2
        assert bootstrap.ensure() is True
        assert len(runtime.shared_memory.group_attempts) == 2


def test_policy_publish_failure_blocks_bootstrap_mutations_until_recovery() -> None:
    account = _Account("me@example.com")
    with _loaded_isolation([account]) as (module, runtime):
        publication_available = False

        def publish_policy(_email: str, enabled: bool, *, force: bool = False) -> bool:
            del force
            if not publication_available:
                return False
            runtime.isolation_policies[runtime.owner_email] = bool(enabled)
            return True

        module._publish_local_account_isolation_policy = publish_policy
        bootstrap = module.AccountIsolationBootstrap()

        assert bootstrap.ensure() is False
        assert runtime.shared_memory.group_writes == []
        assert runtime.shared_memory.isolation_writes == []
        assert runtime.isolation_policies == {}

        publication_available = True
        assert bootstrap.ensure() is True
        assert runtime.isolation_policies == {account.AccountEmail: True}
        assert account.IsolationGroupID > 0
        assert account.IsIsolated is True


def test_active_botting_tree_effective_enabled_policy_overrides_manager_group_zero() -> None:
    account = _Account("me@example.com", group_id=0, isolated=False)
    with _loaded_isolation([account]) as (module, runtime):
        _Settings.assignments[account.AccountEmail] = 0

        class _BottingTreeHost(module.BottingTreeIsolationMixin):
            def __init__(self) -> None:
                self.account_config = types.SimpleNamespace(
                    isolation_enabled=None,
                    sync_party_isolation=True,
                    resolve_isolation_enabled=lambda: True,
                )
                self.isolation_enabled = True

        host = _BottingTreeHost()
        assert host.ApplyAccountIsolation() is True
        assert host.isolation_enabled is True
        assert runtime.isolation_policies == {account.AccountEmail: True}
        bootstrap = module.AccountIsolationBootstrap()
        assert bootstrap.ensure() is True
        assert account.IsolationGroupID > 0
        assert account.IsIsolated is True


def test_active_botting_tree_effective_disabled_policy_blocks_party_reconciliation() -> None:
    account = _Account("me@example.com", group_id=101, party_id=42, isolated=True)
    party_member = _Account("party@example.com", group_id=0, party_id=42, isolated=False)
    with _loaded_isolation([account, party_member]) as (module, runtime):
        _Settings.assignments[party_member.AccountEmail] = 0

        class _BottingTreeHost(module.BottingTreeIsolationMixin):
            def __init__(self) -> None:
                self.account_config = types.SimpleNamespace(
                    isolation_enabled=None,
                    sync_party_isolation=True,
                    resolve_isolation_enabled=lambda: False,
                )
                self.isolation_enabled = False

        runtime.owner_email = party_member.AccountEmail
        runtime.shared_memory.owner_email = party_member.AccountEmail
        host = _BottingTreeHost()
        assert host.ApplyAccountIsolation() is False
        assert runtime.isolation_policies[party_member.AccountEmail] is False

        runtime.owner_email = account.AccountEmail
        runtime.shared_memory.owner_email = account.AccountEmail
        bootstrap = module.AccountIsolationBootstrap()
        assert bootstrap.ensure() is True
        assert bootstrap.ensure() is True
        assert party_member.IsolationGroupID == 0
        assert party_member.IsIsolated is False
        assert runtime.shared_memory.group_writes == []
        assert runtime.shared_memory.isolation_writes == []


def test_botting_tree_policy_registration_clears_when_isolation_is_restored() -> None:
    account = _Account("me@example.com", group_id=77, isolated=True)
    with _loaded_isolation([account]) as (module, runtime):

        class _BottingTreeHost(module.BottingTreeIsolationMixin):
            def __init__(self) -> None:
                self.account_config = types.SimpleNamespace(
                    isolation_enabled=False,
                    sync_party_isolation=True,
                    resolve_isolation_enabled=lambda: False,
                )
                self.isolation_enabled = False
                self.restore_isolation_on_stop = True
                self._previous_isolation_state = None
                self._previous_isolation_group_id = None

        host = _BottingTreeHost()
        host._capture_isolation_state_for_restore()
        assert host.ApplyAccountIsolation() is True
        assert runtime.isolation_policies == {account.AccountEmail: False}
        assert account.IsolationGroupID == 0
        assert account.IsIsolated is False

        assert host.RestoreAccountIsolation() is True
        assert runtime.isolation_policies == {}
        assert account.IsolationGroupID == 77
        assert account.IsIsolated is True


def test_heroai_has_no_independent_account_isolation_setting() -> None:
    heroai_source = (ROOT / "Widgets" / "Automation" / "Multiboxing" / "HeroAI.py").read_bytes().decode("utf-8")
    settings_source = (ROOT / "Py4GWCoreLib" / "HeroAI" / "settings.py").read_bytes().decode("utf-8")
    ui_source = (ROOT / "Py4GWCoreLib" / "HeroAI" / "ui.py").read_bytes().decode("utf-8")

    assert "AccountIsolationEnabled" not in heroai_source
    assert "AccountIsolationEnabled" not in settings_source
    assert "AccountIsolationEnabled" not in ui_source
