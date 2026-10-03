"""Offline tests for guarded Smart Cry lifecycle and receipt ownership."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
from typing import Any
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
CONTROLLER_PATH = SKILLS_DIR / "SmartCryController.py"
SMART_MESMER_PATH = SKILLS_DIR / "SmartMesmer.py"
SMART_CRY_PATH = SKILLS_DIR / "SmartCry.py"


class _Profession(IntEnum):
    _None = 0
    Mesmer = 5


class _Clock:
    now = 1_000


class _Runtime:
    def __init__(self) -> None:
        self.clock = _Clock()
        self.owner_email = "me@example.com"
        self.account_row_present = True
        self.isolation_group_id = 4
        self.group_lookup_error: BaseException | None = None
        self.diagnostics: list[str] = []
        self.queued_callbacks: list[Any] = []
        self.queue_calls = 0
        self.claim_calls: list[tuple[Any, ...]] = []
        self.clear_calls: list[Any] = []
        self.native_calls: list[tuple[int, int]] = []
        self.native_result: Any = True
        self.events: list[Any] = []
        self.combat_enabled = True
        self.disable_combat_on_claim = False
        self.receipt = types.SimpleNamespace(
            slot_index=2,
            owner_email="me@example.com",
            kind_id=11,
            enemy_skill_id=7,
            target_agent_id=10,
            isolation_group_id=4,
            lock_mode=1,
            max_holders=1,
            reentry_policy=0,
            claim_strength=1,
            posted_at_tick64=900,
            expires_at_tick64=1_500,
        )
        self.claim_result = types.SimpleNamespace(receipt=self.receipt, reason="claimed")


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
def _loaded_runtime() -> Iterator[tuple[Any, _Runtime]]:
    prefixes = ("Py4GWCoreLib", "PySystem", "PyAgentEvents")
    original = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
    }
    runtime = _Runtime()
    try:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)

        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("Py4GWCoreLib.HeroAI", ROOT / "Py4GWCoreLib" / "HeroAI")
        _install_package("Py4GWCoreLib.GlobalCache", ROOT / "Py4GWCoreLib" / "GlobalCache")
        _install_package(
            "Py4GWCoreLib.GlobalCache.shared_memory_src",
            ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src",
        )

        root = sys.modules["Py4GWCoreLib"]
        root.Profession = _Profession
        root.ConsoleLog = lambda _module, message, *_args, **_kwargs: runtime.diagnostics.append(str(message))
        root.Player = types.SimpleNamespace(
            GetAccountEmail=lambda: runtime.owner_email,
            GetAgentID=lambda: 1,
        )
        root.Map = types.SimpleNamespace(
            GetMapID=lambda: 1,
            GetInstanceUptime=lambda: 1,
        )

        class _BuildMgr:
            def __init__(self, **kwargs: Any) -> None:
                self.build_name = str(kwargs.get("name", "Build"))
                self._cached_data: Any = None

            def set_cached_data(self, value: Any) -> None:
                self._cached_data = value

            def GetCustomSkill(self, skill_id: int) -> Any:
                return types.SimpleNamespace(
                    SkillID=skill_id,
                    Nature=types.SimpleNamespace(value=0),
                    Conditions=types.SimpleNamespace(),
                )

            def _meets_custom_skill_weapon_requirement(self, _skill_id: int) -> bool:
                return True

            def _meets_custom_skill_shared_conditions(self, _skill_id: int) -> bool:
                return True

            def _validate_target_for_skill_cast(self, _skill_id: int, _target_id: int) -> bool:
                return True

        build_mgr_module = types.ModuleType("Py4GWCoreLib.BuildMgr")
        build_mgr_module.BuildMgr = _BuildMgr
        sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

        skill_module = types.ModuleType("Py4GWCoreLib.Skill")
        skill_module.Skill = types.SimpleNamespace(GetID=lambda _name: 55)
        sys.modules["Py4GWCoreLib.Skill"] = skill_module

        class _SkillBar:
            def GetSlotBySkillID(self, skill_id: int) -> int:
                return 3 if skill_id == 55 else 0

            def GetSkillIDBySlot(self, slot: int) -> int:
                return 55 if slot == 3 else 0

            def QueueGuardedUseSkill(self, callback: Any) -> None:
                runtime.queue_calls += 1
                runtime.queued_callbacks.append(callback)

        class _SharedMemory:
            def __init__(self) -> None:
                self.accounts = types.SimpleNamespace(
                    AccountData=[
                        types.SimpleNamespace(
                            AccountEmail=runtime.owner_email,
                            IsAccount=True,
                            IsolationGroupID=runtime.isolation_group_id,
                        )
                    ]
                )

                def find_slot(account_email: str) -> int:
                    if runtime.account_row_present and account_email == runtime.owner_email:
                        return 0
                    return -1

                self.accounts._find_account_slot_by_email = find_slot

            def GetHeroAIOptionsFromEmail(self, _email: str) -> Any:
                return types.SimpleNamespace(Combat=runtime.combat_enabled, Skills=[True] * 8)

            def GetAccountGroupByEmail(self, _email: str) -> int:
                if runtime.group_lookup_error is not None:
                    raise runtime.group_lookup_error
                if runtime.account_row_present:
                    return int(runtime.isolation_group_id)
                return 0

            def GetAllAccounts(self) -> Any:
                account = self.accounts.AccountData[0]
                account.AccountEmail = runtime.owner_email
                account.IsAccount = bool(runtime.account_row_present)
                account.IsolationGroupID = int(runtime.isolation_group_id)
                return self.accounts

            def TryPostInterruptLock(self, *args: Any) -> Any:
                runtime.claim_calls.append(args)
                if runtime.disable_combat_on_claim:
                    runtime.combat_enabled = False
                return runtime.claim_result

            def ClearInterruptLockIfMatch(self, receipt: Any) -> bool:
                runtime.clear_calls.append(receipt)
                return True

        root.GLOBAL_CACHE = types.SimpleNamespace(
            SkillBar=_SkillBar(),
            ShMem=_SharedMemory(),
            Skill=types.SimpleNamespace(Data=types.SimpleNamespace(GetAoERange=lambda _skill_id: 240.0)),
        )

        intent_sync = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
        intent_sync.get_uncached_tick_count64 = lambda: runtime.clock.now
        intent_sync.tick_is_expired = lambda now, expiry: int(now) >= int(expiry)
        sys.modules[intent_sync.__name__] = intent_sync

        interrupt_module = types.ModuleType("Py4GWCoreLib.HeroAI.interrupt")
        interrupt_module.cast_observer = types.SimpleNamespace()
        sys.modules[interrupt_module.__name__] = interrupt_module

        events_module = types.ModuleType("PyAgentEvents")
        events_module.PyEventType = types.SimpleNamespace(SKILL_ACTIVATED=1)
        events_module.peek_events = lambda: list(runtime.events)
        sys.modules["PyAgentEvents"] = events_module

        sys.modules["PySystem"] = types.SimpleNamespace(
            Console=types.SimpleNamespace(MessageType=types.SimpleNamespace(Info=0)),
        )

        _load_module("Py4GWCoreLib.Builds.Skills.SmartMesmer", SMART_MESMER_PATH)
        _load_module("Py4GWCoreLib.Builds.Skills.SmartCry", SMART_CRY_PATH)
        module = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartCryController",
            CONTROLLER_PATH,
        )
        yield module, runtime
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)
        sys.modules.update(original)


def _request(module: Any) -> Any:
    return module._CryRequest(
        attempt_id=1,
        token=1,
        lifecycle_id=(1, 1, 0),
        composition_generation=0,
        bar_generation=0,
        owner_email="me@example.com",
        isolation_group_id=4,
        player_agent_id=1,
        primary_agent_id=10,
        enemy_skill_id=7,
        observation_identity=(10, 7, 1),
        covered_cast_keys=(module.CryCastKey(10, 7, (10, 7, 1)),),
        enqueue_tick=900,
        deadline_tick=1_150,
        candidate_value=2,
    )


def _assessment() -> Any:
    return types.SimpleNamespace(
        feasible=True,
        enemy_skill_id=7,
        observation_identity=(10, 7, 1),
        interrupt_budget_ms=100,
        enemy_remaining_ms=500,
    )


def _prepare_controller(module: Any, runtime: _Runtime) -> tuple[Any, Any]:
    controller = module.SmartCryController(skill_id=55)
    controller._now_ms = lambda: runtime.clock.now
    controller._lifecycle_id = (1, 1, 0)
    controller._composition_generation = 0
    controller._bar_generation = 0
    controller._token_counter = 1
    request = _request(module)
    controller._request = request
    controller._preclaim_validate = lambda _request, _now: _assessment()
    controller._post_claim_validate = lambda _request, _receipt: _assessment()
    controller._resolve_current_slot = lambda: 3
    controller._strict_assessment = lambda _agent_id, _now_ms: _assessment()
    controller._activation_evidence.matches = lambda _agent_id, _skill_id, _now_ms: True
    return controller, request


def _prepare_preclaim_controller(module: Any, runtime: _Runtime) -> tuple[Any, Any]:
    controller, request = _prepare_controller(module, runtime)
    controller._preclaim_validate = module.SmartCryController._preclaim_validate.__get__(controller)
    controller._runtime_gate = lambda: True
    controller._local_owner_context = lambda: ("me@example.com", 4)
    controller._resolve_current_slot = lambda: 3
    controller._skill_readiness = lambda _slot: True
    controller._target_current_failure_reason = lambda _agent_id, _skill_id: None
    controller._activation_evidence.matches = lambda _agent_id, _skill_id, _now_ms: True
    controller._strict_assessment = lambda _agent_id, _now_ms: _assessment()
    return controller, request


def _invoke(controller: Any, runtime: _Runtime, token: int = 1) -> None:
    def native_use(slot: int, target: int) -> Any:
        runtime.native_calls.append((slot, target))
        if isinstance(runtime.native_result, BaseException):
            raise runtime.native_result
        return runtime.native_result

    controller._on_guarded_action(token, native_use)


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


def test_preclaim_reports_skill_unready_as_the_first_failed_gate() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_preclaim_controller(module, runtime)
        controller._skill_readiness = lambda _slot: False

        assert controller._preclaim_validate(request, runtime.clock.now) is None
        assert controller._preclaim_failure.reason == "skill_unready"
        assert controller._preclaim_failure.details == ("slot=3",)


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        ("target_not_casting", "target_not_casting"),
        ("target_skill_changed", "target_skill_changed"),
    ],
)
def test_preclaim_reports_distinct_target_state_failures(failure: str, expected_reason: str) -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_preclaim_controller(module, runtime)
        controller._target_current_failure_reason = lambda _agent_id, _skill_id: failure

        assert controller._preclaim_validate(request, runtime.clock.now) is None
        assert controller._preclaim_failure.reason == expected_reason


def test_preclaim_reports_onset_mismatch_before_assessment() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_preclaim_controller(module, runtime)
        controller._activation_evidence.matches = lambda _agent_id, _skill_id, _now_ms: False

        assert controller._preclaim_validate(request, runtime.clock.now) is None
        assert controller._preclaim_failure.reason == "onset_unmatched"


def test_preclaim_reports_mechanical_assessment_failure() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_preclaim_controller(module, runtime)
        controller._strict_assessment = lambda _agent_id, _now_ms: types.SimpleNamespace(
            feasible=False,
            reason=types.SimpleNamespace(value="insufficient_time"),
        )

        assert controller._preclaim_validate(request, runtime.clock.now) is None
        assert controller._preclaim_failure.reason == "assessment_infeasible"
        assert controller._preclaim_failure.details == ("assessment_reason=insufficient_time",)


def test_preclaim_failure_terminal_diagnostic_contains_reason_without_account_identity() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_preclaim_controller(module, runtime)
        controller._preclaim_validate = lambda _request, _now: controller._record_validation_failure(
            "skill_unready",
            "slot=3",
        )

        _invoke(controller, runtime)

        assert any(
            "preclaim_failed" in message and "reason=skill_unready" in message for message in runtime.diagnostics
        )
        assert all("me@example.com" not in message for message in runtime.diagnostics)
        assert controller.state is module.CryControllerState.IDLE


def test_no_eligible_candidate_does_not_emit_routine_selection_summary() -> None:
    with _loaded_runtime() as (module, runtime):
        controller = module.SmartCryController(skill_id=55)
        controller._now_ms = lambda: runtime.clock.now
        controller._refresh_lifecycle = lambda: None
        controller._maintain_state = lambda _now: None
        controller._lifecycle_id = (1, 1, 0)
        controller._combat_option_enabled = lambda: True
        controller._local_owner_context_result = lambda: types.SimpleNamespace(
            context=("me@example.com", 4),
            reason=None,
        )
        controller._handled_cast_keys = lambda *_args: set()
        controller._build_selection = lambda *_args: types.SimpleNamespace(
            decision=types.SimpleNamespace(selected=None),
        )

        assert _drain(controller.try_cast()) is False
        runtime.clock.now += 1_000
        assert _drain(controller.try_cast()) is False
        assert runtime.diagnostics == []





@pytest.mark.parametrize(
    ("setup", "expected_reason"),
    [
        ("deadline", "deadline_expired"),
        ("combat", "combat_disabled"),
        ("lifecycle", "lifecycle_changed"),
        ("slot", "cry_slot_changed"),
    ],
)
def test_early_callback_gates_report_their_first_failure(setup: str, expected_reason: str) -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_controller(module, runtime)
        if setup == "deadline":
            runtime.clock.now = request.deadline_tick
        elif setup == "combat":
            runtime.combat_enabled = False
        elif setup == "lifecycle":
            controller._lifecycle_id = (2, 1, 0)
        elif setup == "slot":
            controller._bar_generation = 1

        _invoke(controller, runtime)

        assert any(
            "preclaim_failed" in message and f"reason={expected_reason}" in message for message in runtime.diagnostics
        )
        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert controller.state is module.CryControllerState.IDLE


def test_invalid_callback_token_has_a_bounded_reason() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_controller(module, runtime)

        _invoke(controller, runtime, token=999)

        assert any(
            "preclaim_failed" in message and "reason=request_invalid" in message for message in runtime.diagnostics
        )
        assert controller.pending_request is request


@pytest.mark.parametrize(
    ("owner_email", "account_row_present", "isolation_group_id", "expected_reason"),
    [
        ("", False, 0, "owner_missing"),
        ("me@example.com", False, 0, "account_context_missing"),
        ("me@example.com", True, 0, "isolation_group_missing"),
    ],
)
def test_owner_context_diagnostic_distinguishes_bounded_failures(
    owner_email: str,
    account_row_present: bool,
    isolation_group_id: int,
    expected_reason: str,
) -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.owner_email = owner_email
        runtime.account_row_present = account_row_present
        runtime.isolation_group_id = isolation_group_id

        result = module.SmartCryController._local_owner_context_result()

        assert result.context is None
        assert result.reason == expected_reason

        controller = module.SmartCryController(skill_id=55)
        controller._now_ms = lambda: runtime.clock.now
        controller._combat_option_enabled = lambda: True
        list(controller.try_cast())

        assert any(f"values={expected_reason}" in message for message in runtime.diagnostics)
        assert runtime.claim_calls == []
        assert runtime.native_calls == []


def test_owner_context_diagnostic_accepts_only_the_existing_positive_context() -> None:
    with _loaded_runtime() as (module, runtime):
        result = module.SmartCryController._local_owner_context_result()

        assert result.context == ("me@example.com", 4)
        assert result.reason is None


def test_owner_context_lookup_exception_has_bounded_reason() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.group_lookup_error = RuntimeError("test lookup failure")

        result = module.SmartCryController._local_owner_context_result()

        assert result.context is None
        assert result.reason == "owner_context_lookup_failed"


def test_try_cast_reports_lifecycle_missing_separately() -> None:
    with _loaded_runtime() as (module, runtime):
        controller = module.SmartCryController(skill_id=55)
        controller._now_ms = lambda: runtime.clock.now
        controller._refresh_lifecycle = lambda: None

        list(controller.try_cast())

        assert any("values=lifecycle_missing" in message for message in runtime.diagnostics)
        assert runtime.claim_calls == []
        assert runtime.native_calls == []


@pytest.mark.parametrize(
    ("coverage_kind", "expected_reason"),
    [
        ("missing_key", "primary_covered_key_missing"),
        ("missing_identity", "primary_observation_identity_missing"),
    ],
)
def test_try_cast_fails_closed_without_primary_coverage(
    coverage_kind: str,
    expected_reason: str,
) -> None:
    with _loaded_runtime() as (module, runtime):
        controller = module.SmartCryController(skill_id=55)
        controller._now_ms = lambda: runtime.clock.now
        controller._refresh_lifecycle = lambda: None
        controller._maintain_state = lambda _now_ms: None
        controller._combat_option_enabled = lambda: True
        controller._local_owner_context_result = lambda: types.SimpleNamespace(
            context=("me@example.com", 4),
            reason=None,
        )
        controller._handled_cast_keys = lambda *_args, **_kwargs: set()
        controller._lifecycle_id = (1, 1, 0)

        covered_cast_keys = ()
        if coverage_kind == "missing_identity":
            covered_cast_keys = (module.CryCastKey(10, 7),)
        selected = types.SimpleNamespace(
            primary_agent_id=10,
            primary_enemy_skill_id=7,
            total_interrupt_value=2,
            covered_cast_keys=covered_cast_keys,
        )
        controller._build_selection = lambda _now_ms, _handled: types.SimpleNamespace(
            decision=types.SimpleNamespace(selected=selected),
            primary_assessment=_assessment(),
        )

        list(controller.try_cast())
        assert runtime.queue_calls == 0
        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert controller.pending_request is None
        assert any(f"values={expected_reason}" in message for message in runtime.diagnostics)


def test_guarded_request_has_no_claim_until_its_queued_callback_runs() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_controller(module, runtime)
        controller._queue_guarded_request(request)

        assert runtime.queue_calls == 1
        assert runtime.claim_calls == []
        runtime.queued_callbacks[0](lambda _slot, _target: True)
        assert len(runtime.claim_calls) == 1


def test_successful_native_true_is_submitted_but_not_called_interrupt_success() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        runtime.native_result = True
        _invoke(controller, runtime)

        assert runtime.native_calls == [(3, 10)]
        assert controller.native_result is True
        assert controller.state is module.CryControllerState.SUBMITTED
        assert controller.d0_receipt is runtime.receipt
        assert runtime.clear_calls == []


def test_native_false_is_uncertain_and_keeps_receipt_until_natural_expiry() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        runtime.native_result = False
        _invoke(controller, runtime)

        assert controller.native_result is False
        assert controller.state is module.CryControllerState.UNCERTAIN
        assert controller.d0_receipt is runtime.receipt
        assert runtime.clear_calls == []
        assert controller.pending_request is None
        assert controller.has_active_dispatch() is False
        assert controller._post_submit_deadline is None

        runtime.clock.now = 1_201
        controller.update_lifecycle()
        assert runtime.clear_calls == []
        assert controller.d0_receipt is runtime.receipt

        runtime.clock.now = runtime.receipt.expires_at_tick64
        controller.update_lifecycle()
        assert runtime.clear_calls == []
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE
        assert any("receipt_expired" in message and "lease" in message for message in runtime.diagnostics)


@pytest.mark.parametrize(
    ("remaining_ms", "expected_lease_ms"),
    [(800, 900), (10_000, 10_100), (10_001, None)],
)
def test_required_lease_uses_fresh_remaining_window_and_controller_cap(
    remaining_ms: int,
    expected_lease_ms: int | None,
) -> None:
    with _loaded_runtime() as (module, _runtime):
        controller = module.SmartCryController(skill_id=55)
        assessment = types.SimpleNamespace(
            interrupt_budget_ms=400,
            enemy_remaining_ms=remaining_ms,
        )

        assert controller._required_lease_ms(assessment, 1_000) == expected_lease_ms


@pytest.mark.parametrize(
    "assessment",
    [
        types.SimpleNamespace(interrupt_budget_ms="400", enemy_remaining_ms=800),
        types.SimpleNamespace(interrupt_budget_ms=400.0, enemy_remaining_ms=800),
        types.SimpleNamespace(interrupt_budget_ms=0, enemy_remaining_ms=800),
        types.SimpleNamespace(interrupt_budget_ms=400, enemy_remaining_ms=424),
    ],
)
def test_malformed_or_infeasible_lease_is_rejected_without_claim(
    assessment: Any,
) -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        controller._preclaim_validate = lambda _request, _now: assessment

        _invoke(controller, runtime)

        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert runtime.clear_calls == []
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE


def test_callback_lease_uses_the_callback_time_assessment_not_a_queued_value() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        callback_assessment = types.SimpleNamespace(
            feasible=True,
            enemy_skill_id=7,
            observation_identity=(10, 7, 1),
            interrupt_budget_ms=400,
            enemy_remaining_ms=800,
        )
        observed: list[Any] = []
        controller._preclaim_validate = lambda _request, _now: callback_assessment
        controller._post_claim_validate = lambda _request, _receipt: callback_assessment
        controller._required_lease_ms = lambda assessment, now_ms: (
            observed.append(assessment) or module.SmartCryController._required_lease_ms(controller, assessment, now_ms)
        )

        controller._request = _request(module)
        _invoke(controller, runtime)

        assert observed
        assert observed[0] is callback_assessment
        assert runtime.claim_calls == [("me@example.com", 7, 10, 1_900, 4)]


def test_live_post_native_receipt_is_passive_and_does_not_queue_a_second_local_cast() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        _invoke(controller, runtime)

        assert controller.pending_request is None
        assert controller.has_active_dispatch() is False
        assert controller.build_interrupt_proposal() is None
        assert _drain(controller.try_cast()) is False
        assert controller.state is module.CryControllerState.SUBMITTED
        assert runtime.queue_calls == 0
        assert len(runtime.claim_calls) == 1
        assert len(runtime.native_calls) == 1
        assert runtime.clear_calls == []


def test_preclaim_failure_makes_no_native_call_and_no_release_attempt() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        controller._preclaim_validate = lambda _request, _now: None
        _invoke(controller, runtime)

        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert runtime.clear_calls == []
        assert controller.state is module.CryControllerState.IDLE


def test_combat_disabled_before_guarded_callback_does_not_claim_or_cast() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_controller(module, runtime)
        controller._queue_guarded_request(request)
        runtime.combat_enabled = False

        runtime.queued_callbacks[0](lambda _slot, _target: True)

        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert runtime.clear_calls == []
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE


def test_combat_disabled_after_claim_exactly_releases_before_native() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        runtime.disable_combat_on_claim = True

        _invoke(controller, runtime)

        assert len(runtime.claim_calls) == 1
        assert runtime.native_calls == []
        assert runtime.clear_calls == [runtime.receipt]
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE


def test_postclaim_failure_exactly_releases_the_claim() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        controller._post_claim_validate = lambda _request, _receipt: None
        _invoke(controller, runtime)

        assert runtime.native_calls == []
        assert runtime.clear_calls == [runtime.receipt]
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE


def test_final_native_boundary_releases_when_controlled_clock_consumes_lease_reserve() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)

        def slow_final_assessment(_agent_id: int, _now_ms: int) -> Any:
            runtime.clock.now = 1_400
            return _assessment()

        controller._strict_assessment = slow_final_assessment

        _invoke(controller, runtime)

        assert len(runtime.claim_calls) == 1
        assert runtime.native_calls == []
        assert runtime.clear_calls == [runtime.receipt]
        assert controller.d0_receipt is None
        assert controller.state is module.CryControllerState.IDLE


def test_old_callback_token_cannot_consume_a_newer_request() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, old_request = _prepare_controller(module, runtime)
        new_request = replace(old_request, token=2, attempt_id=2)
        controller._request = new_request
        controller._token_counter = 2
        _invoke(controller, runtime, token=old_request.token)

        assert controller.pending_request is new_request
        assert runtime.claim_calls == []
        assert runtime.native_calls == []


def test_exception_during_native_call_retains_receipt_as_uncertain() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        runtime.native_result = RuntimeError("native boundary")
        _invoke(controller, runtime)

        assert controller.state is module.CryControllerState.UNCERTAIN
        assert controller.d0_receipt is runtime.receipt
        assert runtime.clear_calls == []


def test_dispose_invalidates_queued_work_before_callback_execution() -> None:
    with _loaded_runtime() as (module, runtime):
        controller, request = _prepare_controller(module, runtime)
        controller._queue_guarded_request(request)
        controller.dispose("removed")
        runtime.queued_callbacks[0](lambda _slot, _target: True)

        assert runtime.claim_calls == []
        assert runtime.native_calls == []
        assert controller.pending_request is None


def test_activation_adapter_accepts_matching_onset_once_and_rejects_conflicts() -> None:
    with _loaded_runtime() as (module, runtime):
        observer = types.SimpleNamespace(calls=[])

        def record(*args: Any, **kwargs: Any) -> None:
            observer.calls.append((args, kwargs))

        observer.record_observed_onset = record
        adapter = module.ActivationEvidenceAdapter(max_age_ms=100)
        runtime.events[:] = [
            types.SimpleNamespace(
                timestamp=950,
                event_type=1,
                agent_id=10,
                value=7,
                target_id=1,
                float_value=0.0,
            )
        ]
        assert adapter.update(1_000, observer) is True
        assert adapter.matches(10, 7, 1_000) is True
        assert len(observer.calls) == 1

        adapter.update(1_000, observer)
        assert len(observer.calls) == 1

        runtime.events.append(
            types.SimpleNamespace(
                timestamp=950,
                event_type=1,
                agent_id=10,
                value=8,
                target_id=1,
                float_value=0.0,
            )
        )
        adapter.update(1_000, observer)
        assert adapter.matches(10, 7, 1_000) is False
        assert adapter.matches(10, 8, 1_000) is False
        assert adapter.matches(10, 7, 1_101) is False


@pytest.mark.parametrize("result", [True, False, RuntimeError("native")])
def test_every_native_outcome_retains_receipt_past_the_old_cleanup_window(
    result: Any,
) -> None:
    with _loaded_runtime() as (module, runtime):
        controller, _request_value = _prepare_controller(module, runtime)
        runtime.native_result = result
        _invoke(controller, runtime)
        assert runtime.clear_calls == []
        assert controller.d0_receipt is runtime.receipt

        runtime.clock.now = 1_201
        controller.update_lifecycle()

        assert runtime.clear_calls == []
        assert controller.d0_receipt is runtime.receipt
