"""Focused D2C tests for local arbitration and Complicate runtime ownership."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from enum import IntEnum
from pathlib import Path
from typing import Any
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"


class _Profession(IntEnum):
    _None = 0
    Mesmer = 5


class _Attribute(IntEnum):
    DominationMagic = 2


class _Allegiance(IntEnum):
    Enemy = 3


class _AssessmentReason(str, Enum):
    FEASIBLE = "feasible"


class _OnsetConfidence(str, Enum):
    CONFIRMED = "confirmed_local_onset"


@dataclass(frozen=True, slots=True)
class _Assessment:
    feasible: bool
    reason: _AssessmentReason
    strict: bool
    target_agent_id: int
    our_skill_id: int
    enemy_skill_id: int
    observation_identity: tuple[int, int, int]
    observation_age_ms: int
    onset_confidence: _OnsetConfidence
    enemy_remaining_ms: int
    interrupt_budget_ms: int
    observation_stale: bool = False
    observation_untrusted: bool = False
    timing_invalid: bool = False
    geometry_available: bool = True


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


def _load_shared_memory_support() -> Any:
    name = "_d2c_shared_memory_test_support"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = ROOT / "Examples and tests" / "tests" / "test_shared_memory_intent_cleanup.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _loaded_modules() -> Iterator[tuple[Any, Any, Any, Any, Any]]:
    prefixes = ("Py4GWCoreLib", "PySystem", "PyAgentEvents")
    original = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
    }
    try:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)
        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("Py4GWCoreLib.enums_src", ROOT / "Py4GWCoreLib" / "enums_src")

        root = sys.modules["Py4GWCoreLib"]
        setattr(root, "Profession", _Profession)
        setattr(
            root,
            "Agent",
            types.SimpleNamespace(
                GetAttributes=lambda _agent_id: [types.SimpleNamespace(attribute_id=2, level=15)],
            ),
        )
        setattr(root, "Player", types.SimpleNamespace(GetAgentID=lambda: 1))

        build_mgr = types.ModuleType("Py4GWCoreLib.BuildMgr")

        class _BuildMgr:
            def __init__(self, **kwargs: Any) -> None:
                self.build_name = str(kwargs.get("name", "Build"))

        setattr(build_mgr, "BuildMgr", _BuildMgr)
        sys.modules[build_mgr.__name__] = build_mgr

        skill_module = types.ModuleType("Py4GWCoreLib.Skill")
        setattr(
            skill_module,
            "Skill",
            types.SimpleNamespace(
                GetID=lambda _name: 932,
                GetProgressionData=lambda _skill_id: [("Domination Magic", "Duration", {15: 12.0})],
            ),
        )
        sys.modules[skill_module.__name__] = skill_module
        enum_module = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
        setattr(enum_module, "Attribute", _Attribute)
        setattr(enum_module, "Allegiance", _Allegiance)
        sys.modules[enum_module.__name__] = enum_module

        smart_mesmer = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartMesmer",
            SKILLS_DIR / "SmartMesmer.py",
        )
        smart_cry = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartCry",
            SKILLS_DIR / "SmartCry.py",
        )
        smart_complicate = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartComplicate",
            SKILLS_DIR / "SmartComplicate.py",
        )
        chooser = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartInterruptChooser",
            SKILLS_DIR / "SmartInterruptChooser.py",
        )
        _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartCryController",
            SKILLS_DIR / "SmartCryController.py",
        )
        complicate_controller = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartComplicateController",
            SKILLS_DIR / "SmartComplicateController.py",
        )
        yield smart_mesmer, smart_cry, smart_complicate, chooser, complicate_controller
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
                sys.modules.pop(name, None)
        sys.modules.update(original)


def _enemy(smart_cry: Any, smart_mesmer: Any, agent_id: int, x: float, cast: Any) -> Any:
    return smart_cry.CryEnemyObservation(
        observation=smart_mesmer.EnemyObservation(agent_id, x, 0.0),
        distance_from_player=abs(x),
        current_cast=cast,
    )


def _cry_proposal(
    smart_cry: Any,
    smart_mesmer: Any,
    chooser: Any,
    *,
    agent_id: int,
    primary_skill_id: int = 100,
    collateral: tuple[int, ...] = (),
) -> Any:
    def cast(agent: int, skill_id: int, value: int) -> Any:
        evidence = smart_cry.CryInterruptEvidence(
            target_agent_id=agent,
            enemy_skill_id=skill_id,
            mechanically_feasible=True,
            timing_trusted=True,
            observation_identity=(agent, skill_id, 1),
            observation_age_ms=100,
            onset_confidence=smart_cry.CryOnsetConfidence.TRUSTED,
        )
        return smart_cry.CryCastObservation(
            enemy_skill_id=skill_id,
            interrupt=evidence,
            value_override=value,
            value_reason="d2c_test",
        )

    enemies = [_enemy(smart_cry, smart_mesmer, agent_id, 0.0, cast(agent_id, primary_skill_id, 2))]
    for index, value in enumerate(collateral, start=1):
        enemy_id = agent_id + index
        enemies.append(
            _enemy(
                smart_cry,
                smart_mesmer,
                enemy_id,
                float(index),
                cast(enemy_id, primary_skill_id + index, value),
            )
        )
    snapshot = smart_mesmer.CombatSnapshot(
        enemies=tuple(enemy.observation for enemy in enemies),
        observed_at=0.0,
        lifecycle_id="d2c-test",
    )
    proposal = chooser.SmartCryInterruptProposal.from_smart_cry(
        snapshot,
        enemies,
        cry_radius=4.0,
        cast_range=20.0,
        interrupt_skill_id=55,
    )
    assert proposal is not None
    return proposal


def _complicate_proposal(smart_cry: Any, smart_mesmer: Any, smart_complicate: Any, chooser: Any, *, agent_id: int):
    cry_proposal = _cry_proposal(smart_cry, smart_mesmer, chooser, agent_id=agent_id)
    evaluation = cry_proposal.evaluation
    value = smart_complicate.ComplicateCastValue.from_smart_cry_evaluation(
        evaluation,
        expected_agent_id=agent_id,
        expected_enemy_skill_id=100,
    )
    assessment = _Assessment(
        feasible=True,
        reason=_AssessmentReason.FEASIBLE,
        strict=True,
        target_agent_id=agent_id,
        our_skill_id=932,
        enemy_skill_id=100,
        observation_identity=(agent_id, 100, 1),
        observation_age_ms=100,
        onset_confidence=_OnsetConfidence.CONFIRMED,
        enemy_remaining_ms=800,
        interrupt_budget_ms=400,
    )
    decision = smart_complicate.evaluate_smart_complicate(
        (
            smart_complicate.ComplicateCandidateObservation(
                primary_agent_id=agent_id,
                primary_enemy_skill_id=100,
                mechanical_assessment=smart_complicate.ComplicateInterruptEvidence.from_assessment(assessment),
                primary_value=value,
            ),
        )
    )
    assert decision.selected is not None
    return chooser.SmartComplicateInterruptProposal(decision.selected)


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


class _Handler:
    def __init__(self, proposal: Any, *, active: bool = False) -> None:
        self.proposal = proposal
        self.active = active
        self.build_calls = 0
        self.selected: list[Any] = []

    def has_active_dispatch(self) -> bool:
        return self.active

    def build_interrupt_proposal(self) -> Any:
        self.build_calls += 1
        return self.proposal

    def try_cast_selected(self, proposal: Any):
        if False:
            yield
        self.selected.append(proposal)
        return True


class _D0Runtime:
    def __init__(self) -> None:
        self.active_receipt: Any = None
        self.claim_calls: list[tuple[Any, ...]] = []
        self.clear_calls: list[Any] = []

    def TryPostInterruptLock(self, *args: Any) -> Any:
        self.claim_calls.append(args)
        if self.active_receipt is not None:
            return types.SimpleNamespace(receipt=None, reason="conflict")
        owner_email, enemy_skill_id, target_agent_id, expires_at_tick, isolation_group_id = args
        self.active_receipt = types.SimpleNamespace(
            kind_id=11,
            owner_email=owner_email,
            enemy_skill_id=enemy_skill_id,
            target_agent_id=target_agent_id,
            isolation_group_id=isolation_group_id,
            posted_at_tick64=900,
            expires_at_tick64=expires_at_tick,
        )
        return types.SimpleNamespace(receipt=self.active_receipt, reason="claimed")

    def ClearInterruptLockIfMatch(self, receipt: Any) -> bool:
        self.clear_calls.append(receipt)
        if receipt is not self.active_receipt:
            return False
        self.active_receipt = None
        return True


def _prepare_guarded_controller(controller: Any, controller_module: Any, owner_email: str) -> Any:
    smart_cry_controller = sys.modules["Py4GWCoreLib.Builds.Skills.SmartCryController"]
    request = smart_cry_controller._CryRequest(
        attempt_id=1,
        token=1,
        lifecycle_id=(1, 1, 0),
        composition_generation=0,
        bar_generation=0,
        owner_email=owner_email,
        isolation_group_id=4,
        player_agent_id=1,
        primary_agent_id=10,
        enemy_skill_id=100,
        observation_identity=(10, 100, 1),
        covered_cast_keys=(smart_cry_controller.CryCastKey(10, 100, (10, 100, 1)),),
        enqueue_tick=900,
        deadline_tick=1_150,
        candidate_value=0,
    )
    assessment = _Assessment(
        feasible=True,
        reason=_AssessmentReason.FEASIBLE,
        strict=True,
        target_agent_id=10,
        our_skill_id=int(controller.skill_id),
        enemy_skill_id=100,
        observation_identity=(10, 100, 1),
        observation_age_ms=100,
        onset_confidence=_OnsetConfidence.CONFIRMED,
        enemy_remaining_ms=800,
        interrupt_budget_ms=400,
    )
    controller._now_ms = lambda: 1_000
    controller._lifecycle_id = (1, 1, 0)
    controller._composition_generation = 0
    controller._bar_generation = 0
    controller._token_counter = 1
    controller._request = request
    controller._combat_option_enabled = lambda: True
    controller._preclaim_validate = lambda _request, _now_ms: assessment
    controller._post_claim_validate = lambda _request, _receipt: assessment
    controller._resolve_current_slot = lambda: 3
    controller._strict_assessment = lambda _agent_id, _now_ms: assessment
    controller._activation_evidence.matches = lambda _agent_id, _skill_id, _now_ms: True
    return request


def _configure_real_complicate_runtime() -> tuple[Any, Any, Any]:
    """Install deterministic game observations around the production D0 table helper."""

    support = _load_shared_memory_support()
    support._Clock.value = 1_000
    support._LiveClock.reset()
    support._LiveClock.value = 1_000
    accounts = support._new_accounts()

    state = types.SimpleNamespace(
        now=1_000,
        combat=True,
        toggle=True,
        can_cast=True,
        recharge=0.0,
        current_skill_id=932,
        enemy_skill_id=100,
        enemy_valid=True,
        enemy_casting=True,
        enemy_x=100.0,
        observation_sequence=1,
        enemy_remaining_ms=800,
        interrupt_budget_ms=100,
        enemy_dead=False,
        enemy_knocked_down=False,
        disable_combat_on_claim=False,
        callbacks=[],
        native_calls=[],
        clear_calls=[],
    )

    class _SharedMemory(support._SharedMemoryWrapper):
        def ClearInterruptLockIfMatch(self, receipt: Any) -> bool:
            state.clear_calls.append(receipt)
            return super().ClearInterruptLockIfMatch(receipt)

        def GetHeroAIOptionsFromEmail(self, _owner_email: str) -> Any:
            skills = [True] * 8
            skills[2] = state.toggle
            return types.SimpleNamespace(Combat=state.combat, Skills=skills)

        def TryPostInterruptLock(self, *args: Any) -> Any:
            result = super().TryPostInterruptLock(*args)
            if state.disable_combat_on_claim and result.receipt is not None:
                state.combat = False
            return result

    shmem = _SharedMemory(accounts)
    root: Any = sys.modules["Py4GWCoreLib"]
    root.ConsoleLog = lambda *_args, **_kwargs: None
    root.Player = types.SimpleNamespace(
        GetAccountEmail=lambda: support.OWNER,
        GetAgentID=lambda: 1,
        GetXY=lambda: (0.0, 0.0),
    )
    root.Map = types.SimpleNamespace(
        IsMapReady=lambda: True,
        IsExplorable=lambda: True,
        IsInCinematic=lambda: False,
        GetMapID=lambda: 1,
        GetInstanceUptime=lambda: state.now,
    )
    root.Range = types.SimpleNamespace(Spellcast=types.SimpleNamespace(value=1_248.0))
    root.AgentArray = types.SimpleNamespace(GetEnemyArray=lambda: [10] if state.enemy_valid else [])
    root.Agent = types.SimpleNamespace(
        GetAttributes=lambda _agent_id: [types.SimpleNamespace(attribute_id=2, level=15)],
        IsValid=lambda agent_id: int(agent_id) == 1 or state.enemy_valid and int(agent_id) == 10,
        IsDead=lambda agent_id: state.enemy_dead if int(agent_id) == 10 else False,
        IsKnockedDown=lambda agent_id: state.enemy_knocked_down if int(agent_id) == 10 else False,
        IsCasting=lambda agent_id: state.enemy_casting if int(agent_id) == 10 else False,
        GetCastingSkillID=lambda agent_id: state.enemy_skill_id if int(agent_id) == 10 else 0,
        GetXY=lambda agent_id: (state.enemy_x, 0.0) if int(agent_id) == 10 else (0.0, 0.0),
        GetAllegiance=lambda _agent_id: _Allegiance.Enemy,
    )
    root.Routines = types.SimpleNamespace(
        Checks=types.SimpleNamespace(
            Map=types.SimpleNamespace(MapValid=lambda: True),
            Player=types.SimpleNamespace(CanAct=lambda: True),
            Skills=types.SimpleNamespace(CanCast=lambda: state.can_cast),
        )
    )

    class _SkillBar:
        def GetSlotBySkillID(self, skill_id: int) -> int:
            return 3 if int(skill_id) == state.current_skill_id else 0

        def GetSkillIDBySlot(self, slot: int) -> int:
            return state.current_skill_id if int(slot) == 3 else 0

        def GetCasting(self) -> bool:
            return False

        def GetSkillData(self, _slot: int) -> Any:
            return types.SimpleNamespace(recharge=state.recharge)

        def QueueGuardedUseSkill(self, callback: Any) -> None:
            state.callbacks.append(callback)

    root.GLOBAL_CACHE = types.SimpleNamespace(
        ShMem=shmem,
        SkillBar=_SkillBar(),
        Skill=types.SimpleNamespace(Data=types.SimpleNamespace(GetAoERange=lambda _skill_id: 240.0)),
    )

    intent_sync: Any = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
    intent_sync.get_uncached_tick_count64 = lambda: state.now
    intent_sync.tick_is_expired = lambda now, expiry: int(now) >= int(expiry)
    sys.modules[intent_sync.__name__] = intent_sync

    def assessment() -> _Assessment:
        return _Assessment(
            feasible=True,
            reason=_AssessmentReason.FEASIBLE,
            strict=True,
            target_agent_id=10,
            our_skill_id=932,
            enemy_skill_id=state.enemy_skill_id,
            observation_identity=(10, state.enemy_skill_id, state.observation_sequence),
            observation_age_ms=100,
            onset_confidence=_OnsetConfidence.CONFIRMED,
            enemy_remaining_ms=state.enemy_remaining_ms,
            interrupt_budget_ms=state.interrupt_budget_ms,
        )

    interrupt_module: Any = sys.modules.get("Py4GWCoreLib.HeroAI.interrupt")
    if interrupt_module is None:
        interrupt_module = types.ModuleType("Py4GWCoreLib.HeroAI.interrupt")
        sys.modules[interrupt_module.__name__] = interrupt_module
    interrupt_module.cast_observer = types.SimpleNamespace(
        get_observation=lambda agent_id, skill_id: types.SimpleNamespace(
            observation_identity=(int(agent_id), int(skill_id), state.observation_sequence)
        ),
        record_observed_onset=lambda *_args, **_kwargs: None,
    )
    interrupt_module.assess_interrupt = lambda **_kwargs: assessment()
    interrupt_module._get_player_fast_casting_level = lambda: 0
    interrupt_module._PING_HANDLER = types.SimpleNamespace(GetCurrentPing=lambda: 50)
    events_module: Any = types.ModuleType("PyAgentEvents")
    events_module.PyEventType = types.SimpleNamespace(SKILL_ACTIVATED=1)
    events_module.peek_events = lambda: [
        types.SimpleNamespace(
            timestamp=state.now,
            event_type=1,
            agent_id=10,
            value=state.enemy_skill_id,
            target_id=1,
            float_value=0.0,
        )
    ]
    sys.modules[events_module.__name__] = events_module

    return state, support, accounts


def _new_real_complicate_controller(controller_module: Any) -> tuple[Any, Any, Any, Any]:
    state, support, accounts = _configure_real_complicate_runtime()
    controller = controller_module.SmartComplicateController()
    controller._validate_target_for_skill_cast = lambda _skill_id, _target_id: True
    controller.CanCastSkillSlot = lambda _slot: state.can_cast
    return controller, state, support, accounts


def _queue_real_complicate(controller: Any, state: Any) -> None:
    assert _drain(controller.try_cast()) is True
    assert len(state.callbacks) == 1


def _submit_real_complicate(controller_module: Any) -> tuple[Any, Any, Any, Any]:
    controller, state, support, accounts = _new_real_complicate_controller(controller_module)
    _queue_real_complicate(controller, state)
    state.callbacks.pop()(lambda slot, target: state.native_calls.append((slot, target)) or True)
    assert state.native_calls == [(3, 10)]
    assert controller.d0_receipt is not None
    return controller, state, support, accounts


def _set_real_time(state: Any, support: Any, now_ms: int) -> None:
    state.now = int(now_ms)
    support._Clock.value = int(now_ms)
    support._LiveClock.value = int(now_ms)


def test_same_primary_chooser_queues_only_the_selected_family() -> None:
    with _loaded_modules() as (smart_mesmer, smart_cry, smart_complicate, chooser, controller_module):
        cry = _Handler(
            _cry_proposal(smart_cry, smart_mesmer, chooser, agent_id=10, collateral=(1,)),
        )
        complicate = _Handler(
            _complicate_proposal(smart_cry, smart_mesmer, smart_complicate, chooser, agent_id=10),
        )

        result = _drain(controller_module.SmartCryComplicateCoordinator().try_cast((cry, complicate)))

        assert result is True
        assert len(cry.selected) == 1
        assert complicate.selected == []
        assert cry.selected[0].family is chooser.SmartInterruptFamily.CRY


def test_different_primary_chooser_queues_one_deterministic_family_only() -> None:
    with _loaded_modules() as (smart_mesmer, smart_cry, smart_complicate, chooser, controller_module):
        cry = _Handler(_cry_proposal(smart_cry, smart_mesmer, chooser, agent_id=20))
        complicate = _Handler(
            _complicate_proposal(smart_cry, smart_mesmer, smart_complicate, chooser, agent_id=10),
        )

        result = _drain(controller_module.SmartCryComplicateCoordinator().try_cast((cry, complicate)))

        assert result is True
        assert cry.selected == []
        assert len(complicate.selected) == 1
        assert complicate.selected[0].family is chooser.SmartInterruptFamily.COMPLICATE


def test_pending_smart_interrupt_owns_reentry_without_building_a_second_proposal() -> None:
    with _loaded_modules() as (smart_mesmer, smart_cry, smart_complicate, chooser, controller_module):
        cry = _Handler(_cry_proposal(smart_cry, smart_mesmer, chooser, agent_id=10), active=True)
        complicate = _Handler(
            _complicate_proposal(smart_cry, smart_mesmer, smart_complicate, chooser, agent_id=10),
        )

        result = _drain(controller_module.SmartCryComplicateCoordinator().try_cast((cry, complicate)))

        assert result is True
        assert cry.build_calls == 0
        assert complicate.build_calls == 0
        assert cry.selected == []
        assert complicate.selected == []


def test_complicate_uses_canonical_id_and_real_attribute_progression_owner() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller = controller_module.SmartComplicateController()

        duration = controller._resolve_disable_duration()

        assert controller.skill_id == 932
        assert duration is not None
        assert duration.attribute_rank == 15
        assert duration.duration_seconds == 12


def test_complicate_reuses_smart_cry_d0_receipt_path_without_overrides() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        smart_cry_controller = sys.modules["Py4GWCoreLib.Builds.Skills.SmartCryController"]
        complicate_controller = controller_module.SmartComplicateController

        assert complicate_controller._try_claim is smart_cry_controller.SmartCryController._try_claim
        assert (
            complicate_controller._receipt_matches_request
            is smart_cry_controller.SmartCryController._receipt_matches_request
        )
        assert complicate_controller._release_receipt is smart_cry_controller.SmartCryController._release_receipt


def test_complicate_reaches_inherited_guarded_callback_and_retains_receipt_after_native() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        root = sys.modules["Py4GWCoreLib"]
        d0 = _D0Runtime()
        setattr(root, "Player", types.SimpleNamespace(GetAgentID=lambda: 1, GetAccountEmail=lambda: "complicate"))
        setattr(root, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=d0))
        _install_package("Py4GWCoreLib.HeroAI", ROOT / "Py4GWCoreLib" / "HeroAI")
        interrupt_module = types.ModuleType("Py4GWCoreLib.HeroAI.interrupt")
        setattr(interrupt_module, "cast_observer", types.SimpleNamespace())
        sys.modules[interrupt_module.__name__] = interrupt_module

        controller = controller_module.SmartComplicateController()
        request = _prepare_guarded_controller(controller, controller_module, "complicate")
        native_calls: list[tuple[int, int]] = []

        controller._on_guarded_action(1, lambda slot, target: native_calls.append((slot, target)) or True)

        assert d0.claim_calls == [("complicate", 100, 10, 1_900, 4)]
        assert native_calls == [(3, 10)]
        receipt = controller.d0_receipt
        assert receipt is d0.active_receipt
        assert controller.pending_request is None
        assert controller.has_active_dispatch() is False
        assert controller._post_submit_deadline is None
        assert d0.clear_calls == []
        assert controller._release_receipt("test_release") is True
        assert d0.clear_calls == [receipt]
        assert controller.d0_receipt is None
        assert request is not controller.pending_request


def test_cry_and_complicate_share_late_d0_enemy_cast_identity_and_only_winner_reaches_native() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        root = sys.modules["Py4GWCoreLib"]
        d0 = _D0Runtime()
        setattr(root, "Player", types.SimpleNamespace(GetAgentID=lambda: 1, GetAccountEmail=lambda: "local"))
        setattr(root, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=d0))
        _install_package("Py4GWCoreLib.HeroAI", ROOT / "Py4GWCoreLib" / "HeroAI")
        interrupt_module = types.ModuleType("Py4GWCoreLib.HeroAI.interrupt")
        setattr(interrupt_module, "cast_observer", types.SimpleNamespace())
        sys.modules[interrupt_module.__name__] = interrupt_module

        cry = controller_module.SmartCryController(skill_id=55)
        complicate = controller_module.SmartComplicateController()
        _prepare_guarded_controller(cry, controller_module, "cry")
        _prepare_guarded_controller(complicate, controller_module, "complicate")
        cry_native: list[tuple[int, int]] = []
        complicate_native: list[tuple[int, int]] = []

        cry._on_guarded_action(1, lambda slot, target: cry_native.append((slot, target)) or True)
        complicate._on_guarded_action(1, lambda slot, target: complicate_native.append((slot, target)) or True)

        assert d0.claim_calls[0][1:3] == (100, 10)
        assert d0.claim_calls[1][1:3] == (100, 10)
        assert cry_native == [(3, 10)]
        assert complicate_native == []
        assert complicate.d0_receipt is None
        receipt = cry.d0_receipt
        assert receipt is d0.active_receipt
        assert cry._release_receipt("test_release") is True
        assert d0.clear_calls == [receipt]


def test_complicate_only_uses_real_d0_and_inherited_validation_boundaries() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, chooser, controller_module):
        state, support, accounts = _configure_real_complicate_runtime()
        controller = controller_module.SmartComplicateController()
        controller._validate_target_for_skill_cast = lambda _skill_id, _target_id: True
        controller.CanCastSkillSlot = lambda _slot: state.can_cast

        assert _drain(controller.try_cast()) is True
        assert controller._attempt_counter == 1
        assert len(state.callbacks) == 1

        callback = state.callbacks.pop()
        callback(lambda slot, target: state.native_calls.append((slot, target)) or True)

        assert state.native_calls == [(3, 10)]
        receipt = controller.d0_receipt
        assert receipt is not None
        assert receipt.kind_id == support.INTERRUPT_KIND
        assert receipt.enemy_skill_id == 100
        assert receipt.target_agent_id == 10
        assert controller._release_receipt("integration_cleanup") is True
        assert not any(intent.Active for intent in accounts.Intents)


def test_real_d0_receipt_still_conflicts_after_the_old_post_submit_window() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, support, accounts = _submit_real_complicate(controller_module)
        receipt = controller.d0_receipt
        assert receipt is not None

        _set_real_time(state, support, 1_101)
        assert _drain(controller.try_cast()) is False
        assert controller.d0_receipt is receipt
        assert state.clear_calls == []

        conflict = accounts.TryPostInterruptLock(
            support.OTHER_OWNER,
            100,
            10,
            int(receipt.expires_at_tick64),
            support.GROUP_ID,
        )
        assert conflict.reason == "conflict"
        assert conflict.receipt is None
        assert accounts.Intents[receipt.slot_index].Active


def test_real_callback_lease_uses_current_assessment_after_proposal_time_changes() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, _accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)

        state.enemy_remaining_ms = 10_000
        state.interrupt_budget_ms = 400
        state.callbacks.pop()(lambda slot, target: state.native_calls.append((slot, target)) or True)

        receipt = controller.d0_receipt
        assert receipt is not None
        assert receipt.expires_at_tick64 == 11_100


def test_real_receipt_expiry_cleans_only_local_state_and_allows_another_d0_claim() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, support, accounts = _submit_real_complicate(controller_module)
        receipt = controller.d0_receipt
        assert receipt is not None

        _set_real_time(state, support, int(receipt.expires_at_tick64))
        controller.update_lifecycle()

        assert controller.d0_receipt is None
        assert controller.pending_request is None
        assert controller.state.value == "idle"
        assert state.clear_calls == []

        replacement = accounts.TryPostInterruptLock(
            support.OTHER_OWNER,
            100,
            10,
            state.now + 500,
            support.GROUP_ID,
        )
        assert replacement.reason == "claimed"
        assert replacement.receipt is not None
        assert accounts.ClearInterruptLockIfMatch(replacement.receipt) is True


def test_same_try_cast_invocation_reuses_controller_after_receipt_expiry() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, support, accounts = _submit_real_complicate(controller_module)
        receipt = controller.d0_receipt
        assert receipt is not None

        _set_real_time(state, support, int(receipt.expires_at_tick64))
        assert _drain(controller.try_cast()) is True

        assert controller.d0_receipt is None
        assert controller.pending_request is not None
        assert len(state.callbacks) == 1
        assert state.clear_calls == []
        controller.cancel_pending("post_expiry_test_cleanup")

        replacement = accounts.TryPostInterruptLock(
            support.OTHER_OWNER,
            100,
            10,
            state.now + 500,
            support.GROUP_ID,
        )
        assert replacement.reason == "claimed"
        assert replacement.receipt is not None
        assert accounts.ClearInterruptLockIfMatch(replacement.receipt) is True


def test_real_post_native_runtime_changes_do_not_exactly_release_the_lease() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, support, _accounts = _submit_real_complicate(controller_module)
        receipt = controller.d0_receipt
        assert receipt is not None

        state.combat = False
        state.enemy_valid = False
        state.enemy_casting = False
        state.enemy_dead = True
        state.enemy_knocked_down = True
        state.enemy_skill_id = 0
        state.observation_sequence = 0
        state.current_skill_id = 931
        state.can_cast = False
        state.recharge = 1.0
        controller.set_skill_slot(4)
        controller.update_lifecycle(1)
        controller.update_lifecycle(2)

        assert _drain(controller.try_cast()) is False
        assert controller.build_interrupt_proposal() is None
        assert controller.d0_receipt is receipt
        assert controller.pending_request is None
        assert controller.has_active_dispatch() is False
        assert state.callbacks == []
        assert state.native_calls == [(3, 10)]
        assert state.clear_calls == []


def test_real_cry_and_complicate_proposals_queue_only_the_chooser_winner() -> None:
    with _loaded_modules() as (smart_mesmer, smart_cry, _smart_complicate, chooser, controller_module):
        state, _support, accounts = _configure_real_complicate_runtime()
        cry = controller_module.SmartCryController(skill_id=55)
        complicate = controller_module.SmartComplicateController()

        def cry_policy() -> Any:
            return smart_cry.CryPolicyParameters(generic_value=2)

        def complicate_policy() -> Any:
            return smart_cry.CryPolicyParameters(generic_value=2, minimum_candidate_value=0)

        cry._selection_policy = cry_policy
        complicate._selection_policy = complicate_policy
        cry._validate_target_for_skill_cast = lambda _skill_id, _target_id: True
        complicate._validate_target_for_skill_cast = lambda _skill_id, _target_id: True
        cry.CanCastSkillSlot = lambda _slot: state.can_cast
        complicate.CanCastSkillSlot = lambda _slot: state.can_cast

        result = _drain(controller_module.SmartCryComplicateCoordinator().try_cast((cry, complicate)))

        assert result is True
        assert len(state.callbacks) == 1
        assert not cry.has_active_dispatch()
        assert complicate.has_active_dispatch()
        assert any(
            family == chooser.SmartInterruptFamily.COMPLICATE.value
            for _tick, (family, _agent_id, _skill_id) in complicate._diagnostic_state.values()
        )

        state.callbacks.pop()(lambda slot, target: state.native_calls.append((slot, target)) or True)
        assert state.native_calls == [(3, 10)]
        assert complicate.d0_receipt is not None
        assert complicate._release_receipt("chooser_integration_cleanup") is True
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_toggle_off_keeps_ownership_but_rejects_selected_dispatch() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, _accounts = _new_real_complicate_controller(controller_module)
        proposal = controller.build_interrupt_proposal()
        assert proposal is not None

        state.toggle = False

        assert _drain(controller.try_cast_selected(proposal)) is False
        assert controller.pending_request is None
        assert controller.d0_receipt is None
        assert state.callbacks == []


def test_complicate_selected_dispatch_rejects_current_slot_change_and_lifecycle_change() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, _accounts = _new_real_complicate_controller(controller_module)
        proposal = controller.build_interrupt_proposal()
        assert proposal is not None
        state.current_skill_id = 931
        assert _drain(controller.try_cast_selected(proposal)) is False
        assert state.callbacks == []

    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, _state, _support, _accounts = _new_real_complicate_controller(controller_module)
        proposal = controller.build_interrupt_proposal()
        assert proposal is not None
        controller.update_lifecycle(1)
        assert _drain(controller.try_cast_selected(proposal)) is False
        assert controller.pending_request is None


def test_complicate_selected_dispatch_rejects_resource_and_recharge_loss() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, _accounts = _new_real_complicate_controller(controller_module)
        proposal = controller.build_interrupt_proposal()
        assert proposal is not None
        state.can_cast = False
        assert _drain(controller.try_cast_selected(proposal)) is False
        assert state.callbacks == []

    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, _accounts = _new_real_complicate_controller(controller_module)
        proposal = controller.build_interrupt_proposal()
        assert proposal is not None
        state.recharge = 1.0
        assert _drain(controller.try_cast_selected(proposal)) is False
        assert state.callbacks == []


def test_complicate_observation_identity_and_current_skill_changes_fail_preclaim_without_d0() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        state.observation_sequence = 2
        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert controller.d0_receipt is None
        assert not any(intent.Active for intent in accounts.Intents)

    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        state.enemy_skill_id = 101
        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert controller.d0_receipt is None
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_range_loss_fails_in_inherited_preclaim_and_combat_gates() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        state.enemy_x = 2_000.0
        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert not any(intent.Active for intent in accounts.Intents)

    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        state.combat = False
        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_postclaim_combat_loss_releases_the_exact_real_receipt() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        state.disable_combat_on_claim = True
        _queue_real_complicate(controller, state)
        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert controller.d0_receipt is None
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_final_boundary_uses_inherited_validator_after_real_claim() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        request = controller.pending_request
        assert request is not None
        assessment = controller._preclaim_validate(request, state.now)
        assert assessment is not None
        lease_ms = controller._required_lease_ms(assessment, state.now)
        assert lease_ms is not None
        claim_result, reason = controller._try_claim(request, state.now + lease_ms)
        assert reason == "claimed"
        receipt = controller._receipt_from_claim_result(claim_result)
        assert receipt is not None
        controller._receipt = receipt
        state.combat = False

        assert controller._final_native_boundary_validate(request, receipt) is None
        assert controller._release_receipt("final_boundary_test") is True
        assert not any(intent.Active for intent in accounts.Intents)


def test_cry_and_complicate_use_the_same_real_d0_enemy_cast_identity() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        _state, support, accounts = _configure_real_complicate_runtime()
        smart_cry_controller = sys.modules["Py4GWCoreLib.Builds.Skills.SmartCryController"]
        cry = controller_module.SmartCryController(skill_id=55)
        complicate = controller_module.SmartComplicateController()

        def request(owner_email: str, attempt_id: int) -> Any:
            return smart_cry_controller._CryRequest(
                attempt_id=attempt_id,
                token=attempt_id,
                lifecycle_id=(1, 1, 0),
                composition_generation=0,
                bar_generation=0,
                owner_email=owner_email,
                isolation_group_id=support.GROUP_ID,
                player_agent_id=1,
                primary_agent_id=10,
                enemy_skill_id=100,
                observation_identity=(10, 100, 1),
                covered_cast_keys=(smart_cry_controller.CryCastKey(10, 100, (10, 100, 1)),),
                enqueue_tick=1_000,
                deadline_tick=1_150,
                candidate_value=1,
            )

        cry_request = request(support.OWNER, 1)
        complicate_request = request(support.OTHER_OWNER, 2)
        first, first_reason = cry._try_claim(cry_request, 1_225)
        second, second_reason = complicate._try_claim(complicate_request, 1_225)

        assert first_reason == "claimed"
        assert first.receipt is not None
        assert second_reason == "conflict"
        assert second.receipt is None
        cry._receipt = first.receipt
        cry._request = cry_request
        assert cry._release_receipt("real_d0_conflict_cleanup") is True
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_pending_reentry_and_cancel_cleanup_leave_no_claimable_work() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, _support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        queued_callback = state.callbacks[0]

        assert _drain(controller.try_cast()) is True
        assert len(state.callbacks) == 1

        controller.cancel_pending("pending_cleanup_test")
        assert controller.pending_request is None
        assert controller.d0_receipt is None
        queued_callback(lambda _slot, _target: state.native_calls.append(True) or True)
        assert state.native_calls == []
        assert not any(intent.Active for intent in accounts.Intents)


def test_complicate_real_d0_conflict_keeps_the_other_client_receipt_and_skips_native() -> None:
    with _loaded_modules() as (_smart_mesmer, _smart_cry, _smart_complicate, _chooser, controller_module):
        controller, state, support, accounts = _new_real_complicate_controller(controller_module)
        _queue_real_complicate(controller, state)
        blocker = accounts.TryPostInterruptLock(
            support.OTHER_OWNER,
            100,
            10,
            1_225,
            support.GROUP_ID,
        )
        assert blocker.reason == "claimed"
        assert blocker.receipt is not None

        state.callbacks.pop()(lambda _slot, _target: state.native_calls.append(True) or True)

        assert state.native_calls == []
        assert controller.d0_receipt is None
        assert accounts.Intents[blocker.receipt.slot_index].Active
        assert accounts.ClearInterruptLockIfMatch(blocker.receipt) is True
        assert not any(intent.Active for intent in accounts.Intents)
