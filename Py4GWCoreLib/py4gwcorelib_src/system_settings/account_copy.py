"""Immediate, account-local System Settings copy support.

The setting schemas remain owned by their existing persistence modules. This module only keeps
runtime metadata describing which existing keys belong to one copyable setting, coordinates both
configured offline accounts and loaded target clients, and renders the shared account picker.
"""

from __future__ import annotations

import time
import uuid

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import PyImGui


_PREPARE = 1
_APPLY = 2
_CANCEL = 3
_RESULT_OK = 1
_TRANSACTION_TIMEOUT_SECONDS = 8.0
_LOCK_TIMEOUT_SECONDS = 12.0
_MUTED = (0.60, 0.60, 0.65, 1.0)
_GOOD = (0.45, 0.85, 0.45, 1.0)
_BAD = (0.90, 0.35, 0.35, 1.0)
_POPUP_ID = "Copy account settings##system_settings_account_copy"


def _log(message: str) -> None:
    try:
        import PySystem

        PySystem.Console.Log("System Settings Copy", message, PySystem.Console.MessageType.Warning)
    except Exception:
        pass


@dataclass(frozen=True)
class SettingsSectionOperation:
    """Overlay effective values into one existing account-scoped INI section."""

    document: str
    section: str
    values: dict[str, object]

    def apply_to_account(self, target_email: str) -> bool:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

            return bool(Settings(self.document, "account").apply_section_to_account(
                self.section,
                self.values,
                target_email,
            ))
        except Exception as exc:
            _log("INI copy failed for %s [%s]: %s" % (self.document, self.section, exc))
            return False


@dataclass(frozen=True)
class JsonPathOperation:
    """Overlay one effective value into an existing account-scoped JSON path."""

    document: str
    path: str
    value: Any
    replace: bool = False

    def apply_to_account(self, target_email: str) -> bool:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

            document = JsonFactory(self.document, "account")
            if self.replace and not document.apply_to_account(self.path, None, target_email):
                return False
            return bool(document.apply_to_account(
                self.path,
                self.value,
                target_email,
            ))
        except Exception as exc:
            _log("JSON copy failed for %s at %s: %s" % (self.document, self.path, exc))
            return False


CopyOperation = SettingsSectionOperation | JsonPathOperation


@dataclass(frozen=True)
class AccountCopySpec:
    """Code-only copy metadata for one private System Settings item."""

    setting_id: str
    label: str
    build_operations: Callable[[], tuple[CopyOperation, ...]]
    apply_runtime: Callable[[], bool]
    settings_documents: tuple[str, ...] = ()
    json_documents: tuple[str, ...] = ()

    def flush_local(self) -> bool:
        """Persist target memory before another client overlays its account files."""

        try:
            from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory
            from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

            for document in self.settings_documents:
                if not Settings(document, "account").save():
                    return False
            for document in self.json_documents:
                if not JsonFactory(document, "account").save():
                    return False
            return True
        except Exception as exc:
            _log("Could not prepare %s: %s" % (self.setting_id, exc))
            return False

    def reload_and_apply(self) -> bool:
        """Reload only this setting's owning documents, then update its live controller."""

        try:
            from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory
            from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

            for document in self.settings_documents:
                if not Settings(document, "account").reload():
                    return False
            for document in self.json_documents:
                if not JsonFactory(document, "account").reload():
                    return False
            return bool(self.apply_runtime())
        except Exception as exc:
            _log("Could not reload/apply %s: %s" % (self.setting_id, exc))
            return False


_specs: dict[str, AccountCopySpec] = {}
_defaults_installed = False


def register_spec(spec: AccountCopySpec) -> None:
    existing = _specs.get(spec.setting_id)
    if existing is not None and existing != spec:
        raise ValueError("Duplicate account-copy setting id: %s" % spec.setting_id)
    _specs[spec.setting_id] = spec


def ensure_default_specs() -> None:
    global _defaults_installed
    if _defaults_installed:
        return
    from . import copy_catalog

    _specs.clear()
    try:
        copy_catalog.register_default_specs()
    except Exception:
        _specs.clear()
        raise
    _defaults_installed = True


def get_spec(setting_id: str) -> Optional[AccountCopySpec]:
    ensure_default_specs()
    return _specs.get(str(setting_id))


@dataclass(frozen=True)
class AccountTarget:
    email: str
    character_name: str
    loaded: bool


def configured_account_targets() -> list[AccountTarget]:
    """Return persisted Settings accounts, annotated with their loaded-client state."""

    current = ""
    try:
        from Py4GWCoreLib.Player import Player

        current = str(Player.GetAccountEmail() or "").strip().casefold()
    except Exception:
        pass

    targets_by_email: dict[str, AccountTarget] = {}
    try:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        for account in GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=True, include_isolated=True) or []:
            if not bool(getattr(account, "IsSlotActive", False)) or not bool(getattr(account, "IsAccount", False)):
                continue
            email = str(getattr(account, "AccountEmail", "") or "").strip()
            normalized = email.casefold()
            if not email or normalized == current:
                continue
            agent_data = getattr(account, "AgentData", None)
            character = str(getattr(agent_data, "CharacterName", "") or "").strip()
            targets_by_email[normalized] = AccountTarget(
                email=email,
                character_name=character,
                loaded=True,
            )
    except Exception:
        pass

    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        for email in Settings.account_emails():
            normalized = email.casefold()
            if not email or normalized == current or normalized in targets_by_email:
                continue
            targets_by_email[normalized] = AccountTarget(
                email=email,
                character_name="",
                loaded=False,
            )
    except Exception:
        pass

    targets = list(targets_by_email.values())
    targets.sort(key=lambda target: (
        not target.loaded,
        (target.character_name or target.email).casefold(),
        target.email.casefold(),
    ))
    return targets


@dataclass
class TargetCopyState:
    email: str
    loaded: bool = False
    status: str = "Preparing"
    detail: str = ""
    deadline: float = 0.0
    write_failed: bool = False

    @property
    def finished(self) -> bool:
        return self.status in ("Applied", "Stored", "Failed", "Timed out")


@dataclass
class CopyTransaction:
    request_id: str
    setting_id: str
    operations: tuple[CopyOperation, ...]
    targets: dict[str, TargetCopyState]

    @property
    def finished(self) -> bool:
        return bool(self.targets) and all(target.finished for target in self.targets.values())


@dataclass
class PreparedCopy:
    sender_email: str
    setting_id: str
    deadline: float


class AccountCopyService:
    """Coordinate prepare/write/reload/apply transactions through shared memory."""

    def __init__(self) -> None:
        self.transaction: Optional[CopyTransaction] = None
        self._prepared: dict[str, PreparedCopy] = {}
        self._prepared_by_setting: dict[str, str] = {}

    @staticmethod
    def _document_tokens(spec: AccountCopySpec) -> set[tuple[str, str]]:
        settings = {("settings", document) for document in spec.settings_documents}
        json = {("json", document) for document in spec.json_documents}
        return settings | json

    def is_setting_locked(self, setting_id: str) -> bool:
        spec = get_spec(setting_id)
        if spec is None:
            return False
        wanted = self._document_tokens(spec)
        for prepared in self._prepared.values():
            prepared_spec = get_spec(prepared.setting_id)
            if prepared_spec is not None and wanted.intersection(self._document_tokens(prepared_spec)):
                return True
        return False

    def is_settings_document_locked(self, document: str) -> bool:
        token = ("settings", str(document))
        for prepared in self._prepared.values():
            prepared_spec = get_spec(prepared.setting_id)
            if prepared_spec is not None and token in self._document_tokens(prepared_spec):
                return True
        return False

    def start_copy(self, setting_id: str, target_emails: list[str]) -> bool:
        if self.transaction is not None and not self.transaction.finished:
            return False
        spec = get_spec(setting_id)
        if spec is None:
            return False
        emails = list(dict.fromkeys(email.strip() for email in target_emails if email.strip()))
        if not emails:
            return False
        try:
            operations = tuple(spec.build_operations())
        except Exception as exc:
            _log("Could not export %s: %s" % (setting_id, exc))
            return False
        if not operations:
            return False

        configured_targets = {
            target.email.casefold(): target
            for target in configured_account_targets()
        }
        now = time.monotonic()
        target_states: dict[str, TargetCopyState] = {}
        for email in emails:
            configured = configured_targets.get(email.casefold())
            loaded = bool(configured.loaded) if configured is not None else False
            target_states[email] = TargetCopyState(
                email=email,
                loaded=loaded,
                status="Preparing" if loaded else "Writing",
                deadline=now + _TRANSACTION_TIMEOUT_SECONDS,
            )
        transaction = CopyTransaction(
            request_id=uuid.uuid4().hex,
            setting_id=setting_id,
            operations=operations,
            targets=target_states,
        )
        self.transaction = transaction
        for target in transaction.targets.values():
            if target.loaded:
                if not self._send_sync(target.email, _PREPARE, transaction.request_id, setting_id):
                    target.status = "Failed"
                    target.detail = "Could not queue prepare request"
                continue

            write_ok = True
            for operation in transaction.operations:
                if not operation.apply_to_account(target.email):
                    write_ok = False
            target.status = "Stored" if write_ok else "Failed"
            target.detail = "Available on next login" if write_ok else "Could not write target settings"
        return True

    def _send_sync(self, receiver: str, phase: int, request_id: str, setting_id: str) -> bool:
        try:
            from Py4GWCoreLib import SharedCommandType
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
            from Py4GWCoreLib.Player import Player

            sender = str(Player.GetAccountEmail() or "").strip()
            return GLOBAL_CACHE.ShMem.SendMessage(
                sender,
                receiver,
                SharedCommandType.AccountSettingsSync,
                (float(phase), 0.0, 0.0, 0.0),
                (request_id, setting_id),
            ) >= 0
        except Exception:
            return False

    def _send_result(
        self,
        receiver: str,
        phase: int,
        request_id: str,
        setting_id: str,
        ok: bool,
        detail: str = "",
    ) -> bool:
        try:
            from Py4GWCoreLib import SharedCommandType
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
            from Py4GWCoreLib.Player import Player

            sender = str(Player.GetAccountEmail() or "").strip()
            return GLOBAL_CACHE.ShMem.SendMessage(
                sender,
                receiver,
                SharedCommandType.AccountSettingsSyncResult,
                (float(phase), float(_RESULT_OK if ok else 0), 0.0, 0.0),
                (request_id, setting_id, detail[:63]),
            ) >= 0
        except Exception:
            return False

    @staticmethod
    def _extra_data(message) -> tuple[str, str, str, str]:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            convert = GLOBAL_CACHE.ShMem.GetAllAccounts()._c_wchar_array_to_str
            values = [str(convert(raw) or "") for raw in message.ExtraData]
        except Exception:
            values = ["", "", "", ""]
        values.extend([""] * (4 - len(values)))
        return values[0], values[1], values[2], values[3]

    def handle_sync_message(self, message) -> None:
        request_id, setting_id, _, _ = self._extra_data(message)
        sender = str(getattr(message, "SenderEmail", "") or "").strip()
        phase = int(float(message.Params[0]))
        spec = get_spec(setting_id)
        if spec is None:
            self._send_result(sender, phase, request_id, setting_id, False, "Unknown setting")
            return

        if phase == _PREPARE:
            existing_request = self._prepared_by_setting.get(setting_id)
            if existing_request and existing_request != request_id:
                self._send_result(sender, phase, request_id, setting_id, False, "Setting busy")
                return
            wanted_documents = self._document_tokens(spec)
            for other_request, prepared in self._prepared.items():
                if other_request == request_id:
                    continue
                prepared_spec = get_spec(prepared.setting_id)
                if prepared_spec is not None and wanted_documents.intersection(self._document_tokens(prepared_spec)):
                    self._send_result(sender, phase, request_id, setting_id, False, "Settings file busy")
                    return
            if not spec.flush_local():
                self._send_result(sender, phase, request_id, setting_id, False, "Could not save target")
                return
            self._prepared[request_id] = PreparedCopy(
                sender_email=sender,
                setting_id=setting_id,
                deadline=time.monotonic() + _LOCK_TIMEOUT_SECONDS,
            )
            self._prepared_by_setting[setting_id] = request_id
            self._send_result(sender, phase, request_id, setting_id, True)
            return

        prepared = self._prepared.get(request_id)
        if prepared is None or prepared.sender_email.casefold() != sender.casefold() or prepared.setting_id != setting_id:
            self._send_result(sender, phase, request_id, setting_id, False, "No matching prepare")
            return

        if phase == _CANCEL:
            self._release_prepare(request_id)
            self._send_result(sender, phase, request_id, setting_id, True)
            return

        if phase != _APPLY:
            self._send_result(sender, phase, request_id, setting_id, False, "Unknown phase")
            return

        ok = spec.reload_and_apply()
        self._release_prepare(request_id)
        self._send_result(sender, phase, request_id, setting_id, ok, "" if ok else "Reload/apply failed")

    def handle_result_message(self, message) -> None:
        transaction = self.transaction
        if transaction is None:
            return
        request_id, setting_id, detail, _ = self._extra_data(message)
        if request_id != transaction.request_id or setting_id != transaction.setting_id:
            return
        sender = str(getattr(message, "SenderEmail", "") or "").strip()
        target = transaction.targets.get(sender)
        if target is None:
            target = next(
                (state for email, state in transaction.targets.items() if email.casefold() == sender.casefold()),
                None,
            )
        if target is None or target.finished:
            return

        phase = int(float(message.Params[0]))
        ok = int(float(message.Params[1])) == _RESULT_OK
        if phase == _PREPARE:
            if not ok:
                target.status = "Failed"
                target.detail = detail or "Target preparation failed"
                return
            target.status = "Writing"
            write_ok = True
            for operation in transaction.operations:
                if not operation.apply_to_account(target.email):
                    write_ok = False
            if not write_ok:
                # Cross-document writes are not atomic. Reload even a partial result so the target's
                # memory cannot later autosave stale values over whatever did reach disk.
                target.write_failed = True
                target.detail = "One or more persistence operations failed"
            target.status = "Applying"
            target.deadline = time.monotonic() + _TRANSACTION_TIMEOUT_SECONDS
            if not self._send_sync(target.email, _APPLY, request_id, setting_id):
                target.status = "Failed"
                target.detail = "Could not queue apply request"
                self._send_sync(target.email, _CANCEL, request_id, setting_id)
            return

        if phase == _APPLY:
            if ok and not target.write_failed:
                target.status = "Applied"
                target.detail = ""
            else:
                target.status = "Failed"
                if detail:
                    target.detail = detail
                elif not target.detail:
                    target.detail = "Target apply failed"

    def tick(self) -> None:
        now = time.monotonic()
        for request_id, prepared in list(self._prepared.items()):
            if prepared.deadline <= now:
                self._release_prepare(request_id)

        transaction = self.transaction
        if transaction is None:
            return
        for target in transaction.targets.values():
            if target.finished or target.deadline > now:
                continue
            target.status = "Timed out"
            target.detail = "Target did not acknowledge immediate application"
            self._send_sync(target.email, _CANCEL, transaction.request_id, transaction.setting_id)

    def _release_prepare(self, request_id: str) -> None:
        prepared = self._prepared.pop(request_id, None)
        if prepared is not None and self._prepared_by_setting.get(prepared.setting_id) == request_id:
            self._prepared_by_setting.pop(prepared.setting_id, None)


_service: Optional[AccountCopyService] = None


def get_copy_service() -> AccountCopyService:
    global _service
    if _service is None:
        _service = AccountCopyService()
    return _service


@dataclass
class _CopyUiState:
    setting_id: str = ""
    selected_emails: set[str] = field(default_factory=set)
    open_requested: bool = False


_ui = _CopyUiState()


def draw_copy_header(setting_id: str) -> None:
    """Render the shared copy header and modal for one account-private section."""

    spec = get_spec(setting_id)
    if spec is None:
        PyImGui.text_colored("Account-copy metadata is unavailable.", _BAD)
        PyImGui.separator()
        return

    service = get_copy_service()
    locked = service.is_setting_locked(setting_id)
    PyImGui.text_colored("Private account settings", _MUTED)
    PyImGui.same_line(0, 12)
    PyImGui.begin_disabled(locked)
    if PyImGui.small_button("Copy to accounts...##copy_%s" % setting_id) and not locked:
        _ui.setting_id = setting_id
        _ui.selected_emails.clear()
        _ui.open_requested = True
    PyImGui.end_disabled()
    if locked:
        PyImGui.same_line(0, 8)
        PyImGui.text_colored("Update in progress", _MUTED)
    PyImGui.separator()

    if _ui.setting_id != setting_id:
        return
    if _ui.open_requested:
        PyImGui.open_popup(_POPUP_ID)
        _ui.open_requested = False
    if not PyImGui.begin_popup_modal(_POPUP_ID, True, PyImGui.WindowFlags.AlwaysAutoResize):
        return

    targets = configured_account_targets()
    target_emails = {target.email for target in targets}
    _ui.selected_emails.intersection_update(target_emails)
    PyImGui.text("Copy '%s'" % spec.label)
    PyImGui.text_colored(
        "Loaded clients apply immediately; offline accounts receive the same values for next login.",
        _MUTED,
    )
    PyImGui.separator()

    if PyImGui.small_button("Select all##account_copy_all"):
        _ui.selected_emails = set(target_emails)
    PyImGui.same_line(0, 8)
    if PyImGui.small_button("Clear##account_copy_clear"):
        _ui.selected_emails.clear()

    if not targets:
        PyImGui.text_colored("No other configured accounts are available.", _MUTED)
    for index, target in enumerate(targets):
        checked = target.email in _ui.selected_emails
        state_label = "loaded" if target.loaded else "offline"
        label = "%s [%s]##account_copy_%d" % (target.character_name or target.email, state_label, index)
        new_checked = PyImGui.checkbox(label, checked)
        if new_checked:
            _ui.selected_emails.add(target.email)
        else:
            _ui.selected_emails.discard(target.email)
        if target.character_name:
            PyImGui.same_line(0, 8)
            PyImGui.text_colored(target.email, _MUTED)

    transaction = service.transaction
    active = transaction is not None and transaction.setting_id == setting_id and not transaction.finished
    another_active = transaction is not None and transaction.setting_id != setting_id and not transaction.finished
    if transaction is not None and transaction.setting_id == setting_id:
        PyImGui.separator()
        for target in transaction.targets.values():
            color = _GOOD if target.status in ("Applied", "Stored") else (_BAD if target.finished else _MUTED)
            text = "%s: %s" % (target.email, target.status)
            if target.detail:
                text += " - " + target.detail
            PyImGui.text_colored(text, color)

    PyImGui.separator()
    if another_active:
        PyImGui.text_colored("Another settings copy is still in progress.", _MUTED)
    disabled = active or another_active or not _ui.selected_emails
    PyImGui.begin_disabled(disabled)
    if PyImGui.button("Copy##account_copy_confirm") and not disabled:
        service.start_copy(setting_id, sorted(_ui.selected_emails, key=str.casefold))
    PyImGui.end_disabled()
    PyImGui.same_line(0, 8)
    if PyImGui.button("Close##account_copy_close"):
        PyImGui.close_current_popup()
    PyImGui.end_popup()
