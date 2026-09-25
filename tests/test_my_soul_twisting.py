"""Focused offline tests for the custom Soul Twisting policy."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_MISSING = object()


def _load_subject() -> types.ModuleType:
    module_name = "_my_soul_twisting_policy_test_subject"

    class _Skill:
        _ids: dict[str, int] = {}

        @classmethod
        def GetID(cls, name: str) -> int:
            if name not in cls._ids:
                cls._ids[name] = len(cls._ids) + 1
            return cls._ids[name]

    class _HeroAI_Build:
        pass

    class _SkillsTemplate:
        pass

    class _Allegiance:
        Enemy = 3

    class _Profession(IntEnum):
        _None = 0
        Monk = 3
        Necromancer = 4
        Mesmer = 5
        Ritualist = 8

    class _ThrottledTimer:
        def __init__(self, _throttle_ms: int) -> None:
            pass

        def Stop(self) -> None:
            pass

    class _SpiritModelID:
        SHELTER = 100
        UNION = 101
        DISPLACEMENT = 102

    class _PyEventType:
        SKILL_ACTIVATE_PACKET = 70
        SKILL_ACTIVATED = 1
        INSTANT_SKILL_ACTIVATED = 7
        SKILL_STOPPED = 3
        SKILL_FINISHED = 4
        INTERRUPTED = 6
        CASTTIME = 18
        SKILL_RECHARGE = 80
        SKILL_RECHARGED = 81

    stub_modules: dict[str, types.ModuleType] = {}

    def add_module(name: str, **attributes: Any) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        stub_modules[name] = module
        return module

    corelib = add_module(
        "Py4GWCoreLib",
        Agent=SimpleNamespace(),
        AgentArray=SimpleNamespace(),
        Allegiance=_Allegiance,
        BuildMgr=None,
        GLOBAL_CACHE=SimpleNamespace(),
        Map=SimpleNamespace(),
        Player=SimpleNamespace(),
        Profession=_Profession,
        Range=SimpleNamespace(
            Compass=SimpleNamespace(value=5000.0),
            Earshot=SimpleNamespace(value=1012.0),
            Spellcast=SimpleNamespace(value=1248.0),
        ),
        Routines=SimpleNamespace(),
        SpiritModelID=_SpiritModelID,
        ThrottledTimer=_ThrottledTimer,
        Utils=SimpleNamespace(),
    )
    corelib.__path__ = []
    add_module(
        "PyAgentEvents",
        PyEventType=_PyEventType,
        peek_events=lambda: [],
    )
    add_module("Py4GWCoreLib.Agent", Agent=corelib.Agent)
    add_module("Py4GWCoreLib.Builds").__path__ = []
    add_module("Py4GWCoreLib.Builds.Any").__path__ = []
    add_module("Py4GWCoreLib.Builds.Ritualist").__path__ = []
    add_module("Py4GWCoreLib.Builds.Ritualist.Rt_Any").__path__ = []
    add_module("Py4GWCoreLib.Builds.Any.HeroAI", HeroAI_Build=_HeroAI_Build)
    add_module("Py4GWCoreLib.Builds.Skills", SkillsTemplate=_SkillsTemplate)
    add_module("Py4GWCoreLib.Skill", Skill=_Skill)
    add_module(
        "PySystem",
        get_tick_count64=lambda: 1000,
        Console=SimpleNamespace(MessageType=SimpleNamespace(Info=1)),
    )

    original_modules = {name: sys.modules.get(name, _MISSING) for name in stub_modules}
    original_modules["Py4GWCoreLib.BuildMgr"] = sys.modules.get(
        "Py4GWCoreLib.BuildMgr", _MISSING
    )
    sys.modules.update(stub_modules)
    try:
        buildmgr_path = (
            Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "BuildMgr.py"
        )
        buildmgr_spec = importlib.util.spec_from_file_location(
            "Py4GWCoreLib.BuildMgr", buildmgr_path
        )
        if buildmgr_spec is None or buildmgr_spec.loader is None:
            raise ImportError(f"Could not load {buildmgr_path}")
        buildmgr_module = importlib.util.module_from_spec(buildmgr_spec)
        sys.modules["Py4GWCoreLib.BuildMgr"] = buildmgr_module
        buildmgr_spec.loader.exec_module(buildmgr_module)
        setattr(corelib, "BuildMgr", buildmgr_module.BuildMgr)

        source_path = (
            Path(__file__).resolve().parents[1]
            / "Py4GWCoreLib"
            / "Builds"
            / "Ritualist"
            / "Rt_Any"
            / "My Soul Twisting.py"
        )
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {source_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        setattr(
            module,
            "_matcher_runtime_modules",
            {
                "Py4GWCoreLib": corelib,
                "Py4GWCoreLib.BuildMgr": buildmgr_module,
                "Py4GWCoreLib.Agent": stub_modules["Py4GWCoreLib.Agent"],
            },
        )
        return module
    finally:
        sys.modules.pop(module_name, None)
        for name, original in original_modules.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


ST = _load_subject()


def _effect(
    *, equipped: bool = True, present: bool = True, remaining_ms: int = 10000
) -> Any:
    return ST._EffectObservation(
        equipped=equipped, present=present, remaining_ms=remaining_ms
    )


def _snapshot(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "tick_ms": 1000,
        "map_id": 42,
        "instance_uptime_ms": 5000,
        "context": ST._EncounterContext.PREPARATION,
        "deployment_ready": True,
        "normal_cast_state": True,
        "player_agent_id": 23,
        "local_native_root_id": 12,
        "party_root_ids": frozenset({12}),
        "player_position": (0.0, 0.0),
        "leader_agent_id": 23,
        "leader_valid": True,
        "leader_alive": True,
        "leader_position": (0.0, 0.0),
        "player_energy_fraction": 1.0,
        "soul_twisting": _effect(remaining_ms=10000),
        "boon_of_creation": _effect(remaining_ms=10000),
        "spirits_gift": _effect(remaining_ms=10000),
        "core_spirits": {},
    }
    values.update(overrides)
    return ST._SoulTwistingSnapshot(**values)


def _observation(
    skill_id: int,
    *,
    agent_id: int = 1,
    owner_id: int = 12,
    root_category: Any = None,
    allegiance: int = 1,
    alive: bool = True,
    spawned: bool = True,
    covers: bool = True,
    hp_fraction: float = 0.8,
    position: tuple[float, float] | None = (0.0, 0.0),
    distance_from_player: float | None = 10.0,
    distance_from_leader: float | None = 10.0,
) -> Any:
    if root_category is None:
        root_category = ST._SpiritCategory.PARTY_ROOT_MATCH
    return ST._SpiritObservation(
        skill_id=skill_id,
        model_id=ST._CORE_MODEL_BY_SKILL[skill_id],
        agent_id=agent_id,
        owner_id=owner_id,
        root_category=root_category,
        allegiance=allegiance,
        alive=alive,
        spawned=spawned,
        hp_fraction=hp_fraction,
        position=position,
        distance_from_player=distance_from_player,
        distance_from_leader=distance_from_leader,
        covers_leader=covers,
    )


def _controller(*, equipped: set[int] | None = None) -> Any:
    controller = object.__new__(ST.My_Soul_Twisting)
    ST.Utils.Distance = lambda first, second: (
        ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
    )
    equipped = set(equipped or (ST.Soul_Twisting_ID, *ST._CORE_SKILLS))
    controller.IsSkillEquipped = lambda skill_id: skill_id in equipped
    controller.CanCastSkillID = lambda _skill_id: False
    controller._diagnostic_last_signatures = {}
    controller._diagnostic_online = False
    controller._diagnostic_previous_close = None
    controller._diagnostic_previous_leader_combat = False
    controller._diagnostic_previous_deployment = False
    controller._diagnostic_close_since = None
    controller._diagnostic_leader_combat_since = None
    controller._diagnostic_deployment_since = None
    controller._diagnostic_functional_presence = {}
    controller._diagnostic_functional_spawn_since = {}
    controller._diagnostic_last_heartbeat_ms = 0
    controller._armor_deployment_probes = {}
    controller._armor_deployment_active_cast = None
    controller._armor_deployment_last_terminal_cast = None
    controller._armor_deployment_epoch = None
    controller._armor_deployment_epoch_counter = 0
    controller._armor_deployment_lifecycle = None
    controller._armor_deployment_player_agent_id = 0
    controller._core_rebuild_debounce_skill_id = None
    controller._core_rebuild_debounce_started_ms = None
    controller._core_rebuild_debounce_expired = False
    controller._core_rebuild_debounce_presence = None
    controller._core_rebuild_debounce_scope = None
    controller._core_rebuild_debounce_instance_uptime_ms = None
    return controller


def _configure_world(
    monkeypatch: Any,
    *,
    active_spirits: list[int],
    spirit_data: dict[int, dict[str, Any]],
    party_players: dict[int, int] | None = None,
    party_owner_ids: dict[int, int] | None = None,
    heroes: tuple[int, ...] = (),
    henchmen: tuple[int, ...] = (),
    player_agent_id: int = 23,
    player_position: tuple[float, float] = (0.0, 0.0),
) -> Any:
    party_players = party_players or {1: player_agent_id}
    party_owner_ids = party_owner_ids or {player_agent_id: 12}
    all_positions = {
        agent_id: data.get("position", player_position)
        for agent_id, data in spirit_data.items()
    }
    all_positions[player_agent_id] = player_position
    party_agent_ids = set(party_players.values()) | set(heroes) | set(henchmen)
    for agent_id in party_agent_ids:
        all_positions.setdefault(agent_id, player_position)

    def _spirit(agent_id: int) -> dict[str, Any]:
        return spirit_data[agent_id]

    players = [SimpleNamespace(login_number=login) for login in party_players]
    party = SimpleNamespace(
        GetPlayers=lambda: players,
        Players=SimpleNamespace(
            GetAgentIDByLoginNumber=lambda login: party_players.get(login, 0)
        ),
        GetHeroes=lambda: [SimpleNamespace(agent_id=agent_id) for agent_id in heroes],
        GetHenchmen=lambda: [
            SimpleNamespace(agent_id=agent_id) for agent_id in henchmen
        ],
        GetPartyLeaderID=lambda: player_agent_id,
    )
    monkeypatch.setattr(ST.GLOBAL_CACHE, "Party", party, raising=False)
    monkeypatch.setattr(
        ST.GLOBAL_CACHE,
        "Effects",
        SimpleNamespace(GetEffectTimeRemaining=lambda _agent_id, _skill_id: 10000),
        raising=False,
    )
    monkeypatch.setattr(ST.Player, "GetAgentID", lambda: player_agent_id, raising=False)
    monkeypatch.setattr(ST.Player, "GetXY", lambda: player_position, raising=False)
    monkeypatch.setattr(
        ST.AgentArray,
        "GetSpiritPetArray",
        lambda: list(active_spirits),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "GetPlayerNumber",
        lambda agent_id: _spirit(agent_id)["model_id"],
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "GetOwnerID",
        lambda agent_id: (
            _spirit(agent_id).get("owner_id", 0)
            if agent_id in spirit_data
            else party_owner_ids.get(agent_id, 0)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "GetAllegiance",
        lambda agent_id: _spirit(agent_id).get("allegiance", 1),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "IsAlive",
        lambda agent_id: (
            _spirit(agent_id).get("alive", True) if agent_id in spirit_data else True
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "IsSpawned",
        lambda agent_id: (
            _spirit(agent_id).get("spawned", True) if agent_id in spirit_data else True
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "GetHealth",
        lambda agent_id: (
            _spirit(agent_id).get("hp_fraction", 0.8)
            if agent_id in spirit_data
            else 1.0
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Agent,
        "GetXY",
        lambda agent_id: all_positions.get(agent_id),
        raising=False,
    )
    monkeypatch.setattr(ST.Agent, "IsMoving", lambda _agent_id: False, raising=False)
    monkeypatch.setattr(
        ST.Agent, "IsValid", lambda agent_id: agent_id > 0, raising=False
    )
    monkeypatch.setattr(ST.Agent, "GetEnergy", lambda _agent_id: 1.0, raising=False)
    monkeypatch.setattr(
        ST.Agent, "GetMaxEnergy", lambda _agent_id: 100.0, raising=False
    )
    monkeypatch.setattr(
        ST.Utils,
        "Distance",
        lambda first, second: (
            ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
        ),
        raising=False,
    )
    monkeypatch.setattr(
        ST.Routines,
        "Checks",
        SimpleNamespace(
            Agents=SimpleNamespace(
                InAggro=lambda _range: False,
                HasEffect=lambda _agent_id, _skill_id: True,
            ),
            Skills=SimpleNamespace(CanCast=lambda: True),
        ),
        raising=False,
    )
    controller = _controller()
    controller._cached_data = SimpleNamespace(
        data=SimpleNamespace(
            local_in_aggro=False,
            leader_in_aggro=False,
            party_in_aggro=False,
            in_aggro=True,
        )
    )
    controller.IsCloseToAggro = lambda: False
    return controller


def _finish_generator(generator: Any) -> Any:
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        return stop.value


def _run_intervening_readiness_action(
    controller: Any,
    action: Any,
    snapshot: Any,
) -> None:
    controller._normal_cast_state = lambda: True
    controller._build_snapshot = lambda: snapshot
    controller._observe_armor_deployment = lambda _snapshot: None
    controller._select_action = lambda _snapshot: action
    controller._revalidate_action = lambda _action, _snapshot: (True, "ready")

    def execute_action(_action: Any) -> Any:
        yield
        return True

    controller._execute_action = execute_action
    assert _finish_generator(controller._run_policy("test")) is True
    controller._normal_cast_state = lambda: False
    ST.Routines.Yield = SimpleNamespace(wait=lambda _milliseconds: iter(()))
    assert _finish_generator(controller._run_policy("test")) is False


def test_party_root_classification_is_explicit_and_fail_closed() -> None:
    assert (
        ST._classify_spirit(
            owner_id=12,
            allegiance=1,
            party_root_ids=frozenset({12}),
        )
        is ST._SpiritCategory.PARTY_ROOT_MATCH
    )
    assert (
        ST._classify_spirit(
            owner_id=0,
            allegiance=1,
            party_root_ids=frozenset({12}),
        )
        is ST._SpiritCategory.UNKNOWN
    )
    assert (
        ST._classify_spirit(
            owner_id=999,
            allegiance=1,
            party_root_ids=frozenset({12}),
        )
        is ST._SpiritCategory.UNKNOWN
    )
    assert (
        ST._classify_spirit(
            owner_id=12,
            allegiance=ST.Allegiance.Enemy,
            party_root_ids=frozenset({12}),
        )
        is ST._SpiritCategory.HOSTILE
    )


def test_no_core_spirits_are_deployed_in_shelter_union_displacement_order() -> None:
    controller = _controller()
    snapshot = _snapshot()
    core_spirits: dict[int, tuple[Any, ...]] = {}
    for expected_skill in ST._CORE_SKILLS:
        action = controller._select_action(snapshot)
        assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
        assert action.skill_id == expected_skill
        assert (
            action.reason
            == f"missing_functional_coverage_{ST._CORE_SKILL_NAMES[expected_skill]}"
        )
        core_spirits[expected_skill] = (
            _observation(expected_skill, agent_id=expected_skill, covers=True),
        )
        snapshot = replace(snapshot, core_spirits=dict(core_spirits))


def test_player_and_mercenary_party_roots_are_collected_without_core_spirits(
    monkeypatch: Any,
) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[],
        spirit_data={},
        party_players={1: 23, 2: 24},
        party_owner_ids={23: 12, 24: 45},
    )
    snapshot = controller._build_snapshot()
    assert snapshot.local_native_root_id == 12
    assert snapshot.party_root_ids == frozenset({12, 45})
    action = controller._select_action(snapshot)
    assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
    assert action.skill_id == ST.Shelter_ID


def test_local_native_root_directly_matches_player_owner(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[],
        spirit_data={},
        party_players={1: 23},
        party_owner_ids={23: 12},
    )
    snapshot = controller._build_snapshot()
    assert snapshot.player_agent_id == 23
    assert snapshot.local_native_root_id == 12
    assert snapshot.party_root_ids == frozenset({12})


def test_mercenary_owned_core_can_satisfy_functional_coverage(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 45,
                "position": (0.0, 0.0),
            }
        },
        party_players={1: 23, 2: 24},
        party_owner_ids={23: 12, 24: 45},
    )
    snapshot = controller._build_snapshot()
    observation = snapshot.core_spirits[ST.Shelter_ID][0]
    status = ST._core_status(snapshot, ST.Shelter_ID)
    assert snapshot.party_root_ids == frozenset({12, 45})
    assert observation.root_category is ST._SpiritCategory.PARTY_ROOT_MATCH
    assert status.functional_exists
    assert status.functional_covers
    assert controller._select_action(snapshot).skill_id == ST.Union_ID


def test_mercenary_core_out_of_coverage_is_rebuilt(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 45,
                "position": (2512.01, 0.0),
            }
        },
        party_players={1: 23, 2: 24},
        party_owner_ids={23: 12, 24: 45},
    )
    snapshot = controller._build_snapshot()
    status = ST._core_status(snapshot, ST.Shelter_ID)
    action = controller._select_action(snapshot)
    assert status.functional_exists
    assert not status.functional_covers
    assert status.functional_out_of_coverage
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "rebuild_out_of_coverage_Shelter"


def test_moving_alive_out_of_coverage_core_is_deferred_without_skipping_ahead() -> None:
    controller = _controller()
    snapshot = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={
            ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),),
        },
    )

    action = controller._select_action(snapshot)

    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_skill_id == ST.Shelter_ID
    assert controller._core_rebuild_debounce_started_ms == 1000


def test_movement_stopping_makes_the_deferred_rebuild_eligible() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    stopped = replace(moving, tick_ms=1100, player_moving=False)
    action = controller._select_action(stopped)

    assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "rebuild_out_of_coverage_Shelter"
    assert controller._core_rebuild_debounce_skill_id is None


def test_movement_debounce_expires_while_movement_continues() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    after_grace = replace(
        moving,
        tick_ms=1000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
    )
    action = controller._select_action(after_grace)

    assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "rebuild_out_of_coverage_Shelter"
    assert controller._core_rebuild_debounce_expired


def test_leader_only_movement_starts_the_same_debounce() -> None:
    controller = _controller()
    snapshot = _snapshot(
        leader_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )

    action = controller._select_action(snapshot)

    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.reason == "movement_debounce_Shelter"


def test_debounce_releases_only_at_or_after_exact_grace_expiry() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    just_before = replace(
        moving,
        tick_ms=1000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS - 1,
    )
    assert controller._select_action(just_before).kind is ST._ActionKind.BLOCKED_NO_ACTION

    exact = replace(
        moving,
        tick_ms=1000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
    )
    assert controller._select_action(exact).kind is ST._ActionKind.CORE_DEPLOYMENT

    just_after = replace(
        exact,
        tick_ms=exact.tick_ms + 1,
    )
    assert controller._select_action(just_after).kind is ST._ActionKind.CORE_DEPLOYMENT


def test_debounce_cannot_cross_lifecycle_when_numeric_ids_are_reused() -> None:
    controller = _controller()
    lifecycle_a = _snapshot(
        tick_ms=1000,
        map_id=42,
        instance_uptime_ms=5000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(lifecycle_a).kind is ST._ActionKind.BLOCKED_NO_ACTION

    lifecycle_b = replace(
        lifecycle_a,
        tick_ms=2000,
        instance_uptime_ms=100,
    )
    action = controller._select_action(lifecycle_b)

    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_started_ms == 2000
    assert controller._core_rebuild_debounce_instance_uptime_ms == 100


def test_invalid_lifecycle_clears_and_never_starts_a_debounce() -> None:
    controller = _controller()
    valid = _snapshot(
        tick_ms=500,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(valid).kind is ST._ActionKind.BLOCKED_NO_ACTION

    for tick_ms in (1000, 1900, 2800):
        invalid = replace(
            valid,
            tick_ms=tick_ms,
            map_id=0,
            instance_uptime_ms=0,
        )
        action = controller._select_action(invalid)
        assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
        assert action.skill_id == ST.Shelter_ID
        assert action.reason == "rebuild_out_of_coverage_Shelter"
        assert controller._core_rebuild_debounce_skill_id is None
        assert controller._core_rebuild_debounce_started_ms is None
        assert controller._core_rebuild_debounce_instance_uptime_ms is None


def test_invalid_to_valid_lifecycle_starts_a_fresh_grace_window() -> None:
    controller = _controller()
    invalid = _snapshot(
        tick_ms=1000,
        map_id=0,
        instance_uptime_ms=0,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(invalid).kind is ST._ActionKind.CORE_DEPLOYMENT
    assert controller._select_action(replace(invalid, tick_ms=2800)).kind is ST._ActionKind.CORE_DEPLOYMENT

    valid = replace(
        invalid,
        tick_ms=4000,
        map_id=42,
        instance_uptime_ms=100,
    )
    action = controller._select_action(valid)
    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_started_ms == 4000

    before_expiry = replace(valid, tick_ms=4000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS - 1)
    assert controller._select_action(before_expiry).kind is ST._ActionKind.BLOCKED_NO_ACTION
    exact_expiry = replace(valid, tick_ms=4000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS)
    assert controller._select_action(exact_expiry).kind is ST._ActionKind.CORE_DEPLOYMENT


def test_map_id_change_resets_debounce_with_reused_numeric_ids() -> None:
    controller = _controller()
    first_map = _snapshot(
        tick_ms=1000,
        map_id=42,
        instance_uptime_ms=5000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(first_map).kind is ST._ActionKind.BLOCKED_NO_ACTION

    second_map = replace(
        first_map,
        tick_ms=1100,
        map_id=43,
        instance_uptime_ms=5100,
    )
    action = controller._select_action(second_map)
    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_started_ms == 1100
    assert controller._core_rebuild_debounce_instance_uptime_ms == 5100


def test_same_lifecycle_keeps_the_original_debounce_timestamp() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        instance_uptime_ms=5000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    repeated = replace(moving, tick_ms=1500, instance_uptime_ms=5500)
    assert controller._select_action(repeated).kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert controller._core_rebuild_debounce_started_ms == 1000


def test_changed_out_of_coverage_spirit_restarts_the_debounce() -> None:
    controller = _controller()
    first_spirit = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={
            ST.Shelter_ID: (
                _observation(ST.Shelter_ID, agent_id=101, covers=False),
            )
        },
    )
    assert controller._select_action(first_spirit).kind is ST._ActionKind.BLOCKED_NO_ACTION

    expired = replace(
        first_spirit,
        tick_ms=1000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
    )
    assert controller._select_action(expired).kind is ST._ActionKind.CORE_DEPLOYMENT

    replacement = replace(
        expired,
        tick_ms=2000,
        core_spirits={
            ST.Shelter_ID: (
                _observation(ST.Shelter_ID, agent_id=102, covers=False),
            )
        },
    )
    action = controller._select_action(replacement)

    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_started_ms == 2000
    assert not controller._core_rebuild_debounce_expired


def test_coverage_recovery_clears_defer_without_unnecessary_rebuild() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    covered = replace(
        moving,
        tick_ms=1100,
        core_spirits={
            skill_id: (_observation(skill_id),) for skill_id in ST._CORE_SKILLS
        },
    )
    action = controller._select_action(covered)

    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.reason == "core_package_online_no_action"
    assert controller._core_rebuild_debounce_skill_id is None
    assert not controller._core_rebuild_debounce_expired


def test_absent_or_dead_core_does_not_start_movement_debounce() -> None:
    snapshots = (
        _snapshot(tick_ms=1000, player_moving=True, core_spirits={}),
        _snapshot(
            tick_ms=1000,
            player_moving=True,
            core_spirits={
                ST.Shelter_ID: (
                    _observation(ST.Shelter_ID, alive=False, covers=False),
                )
            },
        ),
    )

    for snapshot in snapshots:
        controller = _controller()
        action = controller._select_action(snapshot)
        assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
        assert action.skill_id == ST.Shelter_ID
        assert action.reason == "missing_functional_coverage_Shelter"
        assert controller._core_rebuild_debounce_skill_id is None


def test_debounce_state_does_not_leak_into_a_later_core_package() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    recovered_package = replace(
        moving,
        tick_ms=1100,
        core_spirits={
            skill_id: (_observation(skill_id),) for skill_id in ST._CORE_SKILLS
        },
    )
    assert (
        controller._select_action(recovered_package).reason
        == "core_package_online_no_action"
    )
    assert controller._core_rebuild_debounce_skill_id is None

    later_repair = replace(
        moving,
        tick_ms=1200,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    action = controller._select_action(later_repair)
    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.skill_id == ST.Shelter_ID
    assert action.reason == "movement_debounce_Shelter"
    assert controller._core_rebuild_debounce_started_ms == 1200


def test_movement_debounce_diagnostics_are_transition_bounded(monkeypatch: Any) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        ST.PySystem.Console,
        "Log",
        lambda _channel, message, _message_type: messages.append(message),
        raising=False,
    )
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )

    controller._select_action(moving)
    controller._select_action(replace(moving, tick_ms=1050))
    controller._select_action(replace(moving, tick_ms=1100))
    controller._select_action(replace(moving, tick_ms=1150, player_moving=False))

    joined = "\n".join(messages)
    assert joined.count("state=started") == 1
    assert "reason=movement_stabilized" in joined


def test_expired_defer_still_uses_fresh_coverage_revalidation() -> None:
    controller = _controller()
    moving = _snapshot(
        tick_ms=1000,
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)},
    )
    assert controller._select_action(moving).kind is ST._ActionKind.BLOCKED_NO_ACTION

    eligible = replace(
        moving,
        tick_ms=1000 + ST.CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
    )
    action = controller._select_action(eligible)
    assert action.kind is ST._ActionKind.CORE_DEPLOYMENT

    recovered = replace(
        eligible,
        tick_ms=eligible.tick_ms + 50,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID),)},
    )
    valid, reason = controller._revalidate_action(action, recovered)

    assert not valid
    assert reason == "functional_core_became_covered_before_cast"
    assert controller._core_rebuild_debounce_skill_id is None


def test_positive_other_party_root_can_satisfy_coverage(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 77,
                "position": (0.0, 0.0),
            }
        },
        party_players={1: 23},
        heroes=(31,),
        party_owner_ids={23: 12, 31: 77},
    )
    snapshot = controller._build_snapshot()
    assert 77 in snapshot.party_root_ids
    assert ST._core_status(snapshot, ST.Shelter_ID).functional_covers


def test_unresolved_foreign_root_does_not_satisfy_coverage() -> None:
    controller = _controller()
    snapshot = _snapshot(
        core_spirits={
            ST.Shelter_ID: (
                _observation(
                    ST.Shelter_ID,
                    owner_id=999,
                    root_category=ST._SpiritCategory.UNKNOWN,
                ),
            )
        }
    )
    action = controller._select_action(snapshot)
    assert action.kind is ST._ActionKind.CORE_DEPLOYMENT
    assert action.skill_id == ST.Shelter_ID


def test_hostile_core_does_not_satisfy_even_when_owner_matches(
    monkeypatch: Any,
) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 12,
                "allegiance": int(ST.Allegiance.Enemy),
                "position": (0.0, 0.0),
            }
        },
    )
    snapshot = controller._build_snapshot()
    observation = snapshot.core_spirits[ST.Shelter_ID][0]
    assert observation.root_category is ST._SpiritCategory.HOSTILE
    assert not ST._core_status(snapshot, ST.Shelter_ID).functional_exists


def test_ownerless_core_does_not_satisfy_coverage(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 0,
                "position": (0.0, 0.0),
            }
        },
    )
    snapshot = controller._build_snapshot()
    observation = snapshot.core_spirits[ST.Shelter_ID][0]
    assert observation.root_category is ST._SpiritCategory.UNKNOWN
    assert not ST._core_status(snapshot, ST.Shelter_ID).functional_exists


def test_mercenary_can_share_the_local_native_root(monkeypatch: Any) -> None:
    controller = _configure_world(
        monkeypatch,
        active_spirits=[101],
        spirit_data={
            101: {
                "model_id": int(ST.SpiritModelID.SHELTER),
                "owner_id": 12,
                "position": (0.0, 0.0),
            }
        },
        party_players={1: 23, 2: 24},
        party_owner_ids={23: 12, 24: 12},
    )
    snapshot = controller._build_snapshot()
    assert snapshot.party_root_ids == frozenset({12})
    assert ST._core_status(snapshot, ST.Shelter_ID).functional_covers


def test_stale_core_plus_covering_copy_is_already_satisfied() -> None:
    controller = _controller()
    snapshot = _snapshot(
        core_spirits={
            ST.Shelter_ID: (
                _observation(
                    ST.Shelter_ID,
                    agent_id=101,
                    covers=False,
                    distance_from_leader=2512.01,
                ),
                _observation(ST.Shelter_ID, agent_id=102, covers=True),
            )
        }
    )
    status = ST._core_status(snapshot, ST.Shelter_ID)
    action = controller._select_action(snapshot)
    assert status.functional_exists
    assert status.functional_covers
    assert action.skill_id == ST.Union_ID


def test_stale_core_revalidation_cancels_when_functional_coverage_appears() -> None:
    controller = _controller()
    initial = _snapshot(
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)}
    )
    action = controller._select_action(initial)
    latest = replace(
        initial,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=True),)},
    )
    valid, reason = controller._revalidate_action(action, latest)
    assert not valid
    assert reason == "functional_core_became_covered_before_cast"


def test_stale_core_revalidation_allows_rebuild_until_covering_copy_appears() -> None:
    controller = _controller()
    snapshot = _snapshot(
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)}
    )
    action = controller._select_action(snapshot)
    valid, reason = controller._revalidate_action(action, snapshot)
    assert valid
    assert reason == "ready"


def test_low_hp_functional_core_still_counts_as_coverage() -> None:
    snapshot = _snapshot(
        core_spirits={
            ST.Shelter_ID: (_observation(ST.Shelter_ID, hp_fraction=0.01, covers=True),)
        }
    )
    status = ST._core_status(snapshot, ST.Shelter_ID)
    assert status.functional_exists
    assert status.functional_covers


def test_coverage_uses_the_existing_2512_radius_and_not_player_movement() -> None:
    assert ST._leader_is_covered(
        distance_to_leader=2512.0,
        leader_valid=True,
        leader_alive=True,
    )
    assert not ST._leader_is_covered(
        distance_to_leader=2512.01,
        leader_valid=True,
        leader_alive=True,
    )
    controller = _controller()
    moving_snapshot = _snapshot(
        player_moving=True,
        core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=True),)},
    )
    assert controller._select_action(moving_snapshot).skill_id == ST.Union_ID


def test_simultaneous_controllers_have_no_build_local_owner_learner() -> None:
    first = _controller()
    second = _controller()
    snapshot = _snapshot(
        core_spirits={
            ST.Shelter_ID: (
                _observation(
                    ST.Shelter_ID,
                    owner_id=999,
                    root_category=ST._SpiritCategory.UNKNOWN,
                ),
            )
        }
    )
    assert first._select_action(snapshot) == second._select_action(snapshot)
    assert "_resolve_self_agent_id" not in ST.My_Soul_Twisting.__dict__
    assert "_learn_from_core_cast" not in ST.My_Soul_Twisting.__dict__
    assert "_refresh_owner_lifecycle" not in ST.My_Soul_Twisting.__dict__
    assert not hasattr(ST, "_OwnerCorrelationContext")
    assert not hasattr(ST, "_OwnerCorrelationCandidate")
    assert hasattr(ST, "PyAgentEvents")
    assert not any(name.startswith("_Owner") for name in vars(ST))
    assert not any("learned" in name for name in vars(first))
    assert not any("learned" in name for name in vars(second))


def test_summon_is_excluded_from_core_policy_actions() -> None:
    controller = _controller(equipped={ST.Summon_Spirits_kurzick_ID})
    action = controller._select_action(_snapshot(core_spirits={}))
    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.skill_id == 0
def _production_controller() -> Any:
    controller = _controller(
        equipped=set(ST._CORE_SKILLS) | {ST.Armor_of_Unfeeling_ID}
    )
    controller.CanCastSkillID = (
        lambda skill_id: skill_id == ST.Armor_of_Unfeeling_ID
    )
    return controller


def _raw_event(
    *,
    timestamp: int,
    event_type: int,
    agent_id: int,
    skill_id: int,
    target_id: int = 0,
    float_value: float = 0.0,
) -> Any:
    return SimpleNamespace(
        timestamp=timestamp,
        event_type=event_type,
        agent_id=agent_id,
        value=skill_id,
        target_id=target_id,
        float_value=float_value,
    )


def _complete_deployment(
    controller: Any,
    monkeypatch: Any,
    events: list[Any],
    *,
    skill_id: int,
    request_at: int,
    packet_at: int,
    activation_at: int,
    finish_at: int,
    candidate_at: int,
    settle_at: int,
    pre_agent_id: int = 10,
    candidate_id: int = 11,
    candidate_position: tuple[float, float] = (10.0, 0.0),
    candidate_spawned: bool = True,
    finish_value: int = 0,
    wrapper_result: bool | None | object = _MISSING,
    retained_core_spirits: dict[int, tuple[Any, ...]] | None = None,
) -> Any:
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    probe = controller._record_armor_deployment_request(
        skill_id,
        _snapshot(
            tick_ms=request_at,
            core_spirits={
                skill_id: (_observation(skill_id, agent_id=pre_agent_id),)
            },
        ),
    )
    assert probe is not None
    if wrapper_result is not _MISSING:
        controller._record_armor_deployment_result(
            skill_id,
            bool(wrapper_result),
            _snapshot(tick_ms=request_at + 1),
        )
    events.extend(
        [
            _raw_event(
                timestamp=packet_at,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=skill_id,
            ),
            _raw_event(
                timestamp=activation_at,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=skill_id,
            ),
            _raw_event(
                timestamp=finish_at,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=finish_value,
            ),
        ]
    )
    base = dict(retained_core_spirits or {})
    base.update({
        skill_id: (
            _observation(skill_id, agent_id=pre_agent_id),
        )
    })
    controller._observe_armor_deployment(
        _snapshot(tick_ms=finish_at, core_spirits=base)
    )
    candidate_snapshot = dict(retained_core_spirits or {})
    candidate_snapshot.update({
        skill_id: (
            _observation(skill_id, agent_id=pre_agent_id),
            _observation(
                skill_id,
                agent_id=candidate_id,
                position=candidate_position,
                spawned=candidate_spawned,
            ),
        )
    })
    controller._observe_armor_deployment(
        _snapshot(tick_ms=candidate_at, core_spirits=candidate_snapshot)
    )
    settled_snapshot = dict(retained_core_spirits or {})
    settled_snapshot.update({
        skill_id: (
            _observation(skill_id, agent_id=pre_agent_id),
            _observation(
                skill_id,
                agent_id=candidate_id,
                position=candidate_position,
                spawned=True,
            ),
        )
    })
    controller._observe_armor_deployment(
        _snapshot(tick_ms=settle_at, core_spirits=settled_snapshot)
    )
    return probe


def _append_controlled_ritual_events(
    events: list[Any],
    *,
    skill_id: int,
    packet_at: int,
    activation_at: int,
    finish_at: int,
    terminal_occurrences: int = 1,
) -> None:
    events.extend(
        [
            _raw_event(
                timestamp=packet_at,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=skill_id,
            ),
            _raw_event(
                timestamp=activation_at,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=skill_id,
            ),
        ]
    )
    events.extend(
        _raw_event(
            timestamp=finish_at,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        )
        for _ in range(terminal_occurrences)
    )


def _start_candidate_settling_probe(
    monkeypatch: Any,
    skill_id: int,
) -> tuple[Any, list[Any], Any, tuple[Any, ...]]:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    pre_existing = _observation(skill_id, agent_id=10)
    probe = controller._record_armor_deployment_request(
        skill_id,
        _snapshot(tick_ms=1000, core_spirits={skill_id: (pre_existing,)}),
    )
    assert probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=skill_id,
        packet_at=1100,
        activation_at=1110,
        finish_at=1200,
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1200, core_spirits={skill_id: (pre_existing,)})
    )
    first_candidate = _observation(
        skill_id,
        agent_id=11,
        position=(10.0, 0.0),
    )
    candidate_spirits = (pre_existing, first_candidate)
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1300, core_spirits={skill_id: candidate_spirits})
    )
    assert probe.settle_until_ms == 2300
    return controller, events, probe, candidate_spirits


def _start_qualified_candidate_probe(
    monkeypatch: Any,
    *,
    request_at: int = 1000,
    packet_at: int = 1200,
    activation_at: int = 1250,
    finish_at: int = 2750,
    candidate_at: int = 4750,
    retained_core_spirits: dict[int, tuple[Any, ...]] | None = None,
) -> tuple[Any, list[Any], Any, dict[int, tuple[Any, ...]]]:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    pre_existing = _observation(ST.Shelter_ID, agent_id=10)
    request_spirits = dict(retained_core_spirits or {})
    request_spirits[ST.Shelter_ID] = (pre_existing,)
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=request_at,
            core_spirits=request_spirits,
        ),
    )
    assert probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=ST.Shelter_ID,
        packet_at=packet_at,
        activation_at=activation_at,
        finish_at=finish_at,
    )
    finish_spirits = dict(retained_core_spirits or {})
    finish_spirits[ST.Shelter_ID] = (pre_existing,)
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=finish_at,
            core_spirits=finish_spirits,
        )
    )
    spirits = dict(retained_core_spirits or {})
    spirits[ST.Shelter_ID] = (
        pre_existing,
        _observation(
            ST.Shelter_ID,
            agent_id=11,
            position=(10.0, 0.0),
        ),
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=candidate_at, core_spirits=spirits)
    )
    assert probe.qualifying_at_ms == candidate_at
    assert probe.settle_until_ms == (
        candidate_at + ST.ARMOR_CANDIDATE_SETTLE_MS
    )
    return controller, events, probe, spirits


def _seed_epoch(
    controller: Any,
    *,
    token_skills: tuple[int, ...] = (ST.Shelter_ID, ST.Union_ID),
    finish_at: int = 1000,
    expires_at: int | None = None,
) -> Any:
    tokens = {
        skill_id: ST._ArmorDeploymentToken(
            skill_id=skill_id,
            model_id=ST._CORE_MODEL_BY_SKILL[skill_id],
            witness_agent_id=100 + index,
            map_id=42,
            instance_uptime_ms=5000,
            player_agent_id=23,
            request_at_ms=finish_at - 300,
            finish_at_ms=finish_at,
            witness_fingerprint=(
                ST._CORE_MODEL_BY_SKILL[skill_id],
                12,
                ST._SpiritCategory.PARTY_ROOT_MATCH.value,
            ),
        )
        for index, skill_id in enumerate(token_skills)
    }
    controller._armor_deployment_epoch = ST._ArmorDeploymentEpoch(
        epoch_id=1,
        map_id=42,
        instance_uptime_ms=5000,
        player_agent_id=23,
        started_at_ms=finish_at,
        expires_at_ms=(
            finish_at + ST.ARMOR_DEPLOYMENT_EPOCH_MS
            if expires_at is None
            else expires_at
        ),
        tokens=tokens,
    )
    controller._armor_deployment_lifecycle = (42, 5000)
    controller._armor_deployment_player_agent_id = 23
    return controller._armor_deployment_epoch


def _full_core_snapshot(
    *,
    tick_ms: int = 2000,
    displacement_id: int = 30,
    player_position: tuple[float, float] = (0.0, 0.0),
) -> Any:
    distance_from_player = abs(player_position[0])
    return _snapshot(
        tick_ms=tick_ms,
        player_position=player_position,
        core_spirits={
            ST.Shelter_ID: (
                _observation(
                    ST.Shelter_ID,
                    agent_id=100,
                    distance_from_player=distance_from_player,
                ),
            ),
            ST.Union_ID: (
                _observation(
                    ST.Union_ID,
                    agent_id=101,
                    distance_from_player=distance_from_player,
                ),
            ),
            ST.Displacement_ID: (
                _observation(
                    ST.Displacement_ID,
                    agent_id=displacement_id,
                    distance_from_player=distance_from_player,
                ),
            ),
        },
    )


def test_production_has_no_superseded_armor_experiment() -> None:
    assert not any(
        name.startswith("_TEMPORARY_") or name.startswith("_ARMOR_DIAGNOSTIC")
        for name in vars(ST)
    )
    assert not hasattr(ST.My_Soul_Twisting, "_observe_armor_snapshot")
    assert not hasattr(ST.My_Soul_Twisting, "_observe_armor_event_probe")
    assert not hasattr(ST.My_Soul_Twisting, "_armor_causal_agent_ids")


def test_valid_event_sequence_issues_one_witness_token(monkeypatch: Any) -> None:
    controller = _production_controller()
    events: list[Any] = []
    probe = _complete_deployment(
        controller,
        monkeypatch,
        events,
        skill_id=ST.Shelter_ID,
        request_at=1000,
        packet_at=1100,
        activation_at=1200,
        finish_at=1500,
        candidate_at=1600,
        settle_at=2600,
    )
    assert [record.event_type for record in probe.event_records] == [
        "SKILL_ACTIVATE_PACKET",
        "SKILL_ACTIVATED",
        "SKILL_FINISHED",
    ]
    assert all(record.controlled for record in probe.event_records)
    assert probe.finish_at_ms == 1500
    assert controller._armor_deployment_probes == {}
    assert controller._armor_deployment_epoch is not None
    assert controller._armor_deployment_epoch.tokens[ST.Shelter_ID].witness_agent_id == 11


def test_nonzero_skill_finished_never_completes_deployment(monkeypatch: Any) -> None:
    controller = _production_controller()
    events: list[Any] = []
    probe = _complete_deployment(
        controller,
        monkeypatch,
        events,
        skill_id=ST.Shelter_ID,
        request_at=1000,
        packet_at=1100,
        activation_at=1200,
        finish_at=1500,
        candidate_at=1600,
        settle_at=2600,
        finish_value=ST.Shelter_ID,
    )
    assert probe.invalid_reason == "finish_value_nonzero"
    assert controller._armor_deployment_epoch is None


def test_wrapper_results_do_not_gate_event_evidence(monkeypatch: Any) -> None:
    for wrapper_result in (True, False):
        controller = _production_controller()
        events: list[Any] = []
        _complete_deployment(
            controller,
            monkeypatch,
            events,
            skill_id=ST.Shelter_ID,
            request_at=1000,
            packet_at=1100,
            activation_at=1200,
            finish_at=1500,
            candidate_at=1600,
            settle_at=2600,
            wrapper_result=wrapper_result,
        )
        assert controller._armor_deployment_epoch is not None


def test_no_events_no_token_and_zero_finish_before_context_is_ignored(
    monkeypatch: Any,
) -> None:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.append(
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        )
    )
    controller._observe_armor_deployment(_snapshot(tick_ms=1100))
    assert probe.finish_at_ms is None
    assert not probe.seen_event_keys
    controller._observe_armor_deployment(_snapshot(tick_ms=2600, core_spirits={}))
    assert controller._armor_deployment_epoch is None
    assert probe.invalid_reason == "activation_sequence_missing_or_late"


def test_foreign_caster_is_not_local_and_lookback_is_bounded(monkeypatch: Any) -> None:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.append(
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=24,
            skill_id=ST.Shelter_ID,
        )
    )
    controller._observe_armor_deployment(_snapshot(tick_ms=1100))
    assert probe.invalid_reason == "foreign_expected_skill_activation"
    assert not probe.event_records[0].controlled

    events[0] = _raw_event(
        timestamp=2500,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
        agent_id=24,
        skill_id=ST.Shelter_ID,
    )
    controller = _production_controller()
    assert (
        controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=5000,
                core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
            ),
        )
        is None
    )

    events[0] = _raw_event(
        timestamp=1000,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
        agent_id=24,
        skill_id=ST.Shelter_ID,
    )
    controller = _production_controller()
    assert (
        controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=5000,
                core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
            ),
        )
        is not None
    )
    events[0] = _raw_event(
        timestamp=1000,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
        agent_id=24,
        skill_id=ST.Shelter_ID,
    )
    controller = _production_controller()
    assert (
        controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=5000,
                core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
            )
        )
        is not None
    )


def test_wrong_order_intervening_skill_stop_interrupt_and_duplicate_terminal(
    monkeypatch: Any,
) -> None:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.append(
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        )
    )
    controller._observe_armor_deployment(_snapshot(tick_ms=1100))
    assert probe.invalid_reason == "activation_before_packet"

    def stopped_probe(terminal_type: int) -> Any:
        local_events: list[Any] = []
        monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(local_events))
        local_controller = _production_controller()
        local_probe = local_controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=1000,
                core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
            ),
        )
        assert local_probe is not None
        local_events.extend(
            [
                _raw_event(
                    timestamp=1100,
                    event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                    agent_id=23,
                    skill_id=ST.Shelter_ID,
                ),
                _raw_event(
                    timestamp=1110,
                    event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                    agent_id=23,
                    skill_id=ST.Shelter_ID,
                ),
                _raw_event(
                    timestamp=1200,
                    event_type=terminal_type,
                    agent_id=23,
                    skill_id=0,
                ),
            ]
        )
        local_controller._observe_armor_deployment(_snapshot(tick_ms=1200))
        return local_probe

    assert stopped_probe(ST.PyAgentEvents.PyEventType.SKILL_STOPPED).invalid_reason == "skill_stopped"
    assert stopped_probe(ST.PyAgentEvents.PyEventType.INTERRUPTED).invalid_reason == "interrupted"

    events.clear()
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=2000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(
        [
            _raw_event(
                timestamp=2100,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=2110,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=2200,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Union_ID,
            ),
        ]
    )
    controller._observe_armor_deployment(_snapshot(tick_ms=2200))
    assert probe.invalid_reason == "intervening_controlled_skill_activation"


def test_peek_is_deduplicated_and_never_drains_or_reconfigures(monkeypatch: Any) -> None:
    events: list[Any] = []
    post_request_events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    calls: list[str] = []
    monkeypatch.setattr(
        ST.PyAgentEvents,
        "peek_events",
        lambda: calls.append("peek") or list(events),
    )
    for name in ("get_and_clear_events", "enable", "disable"):
        monkeypatch.setattr(
            ST.PyAgentEvents,
            name,
            lambda: (_ for _ in ()).throw(AssertionError(name)),
            raising=False,
        )
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(post_request_events)
    controller._observe_armor_deployment(_snapshot(tick_ms=1200))
    controller._observe_armor_deployment(_snapshot(tick_ms=1200))
    assert probe.invalid_reason is None
    assert len(probe.seen_event_keys) == 3
    assert len(calls) >= 3


def test_duplicate_terminals_in_one_peek_snapshot_reject_probe(
    monkeypatch: Any,
) -> None:
    events: list[Any] = []
    post_request_events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(post_request_events)
    controller._observe_armor_deployment(_snapshot(tick_ms=1200))
    assert probe.invalid_reason == "duplicate_terminal_in_snapshot"
    assert controller._armor_deployment_epoch is None


def _exercise_overlapping_deployment_pair(
    monkeypatch: Any,
    *,
    first_skill: int,
    second_skill: int,
) -> tuple[Any, Any, Any]:
    controller, events, first_probe, first_spirits = (
        _start_candidate_settling_probe(monkeypatch, first_skill)
    )
    second_pre_existing = _observation(second_skill, agent_id=20)
    second_probe = controller._record_armor_deployment_request(
        second_skill,
        _snapshot(
            tick_ms=1700,
            core_spirits={
                first_skill: first_spirits,
                second_skill: (second_pre_existing,),
            },
        ),
    )
    assert second_probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=second_skill,
        packet_at=1800,
        activation_at=1810,
        finish_at=2200,
    )
    second_candidate = _observation(
        second_skill,
        agent_id=21,
        position=(10.0, 0.0),
    )

    def current_spirits() -> dict[int, tuple[Any, ...]]:
        return {
            first_skill: first_spirits,
            second_skill: (second_pre_existing, second_candidate),
        }

    controller._observe_armor_deployment(
        _snapshot(tick_ms=2250, core_spirits=current_spirits())
    )
    assert first_probe.invalid_reason is None
    assert second_probe.invalid_reason is None
    assert first_probe.settle_until_ms == 2300
    assert second_probe.finish_at_ms == 2200
    assert second_probe in controller._armor_deployment_probes.values()
    assert any(
        record.association == "other-controlled-cast"
        for record in first_probe.event_records
    )
    assert any(
        record.event_type == "SKILL_FINISHED"
        and record.association == "active-controlled-cast"
        for record in second_probe.event_records
    )

    # peek_events is non-draining; replay after the active-cast pointer clears.
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2299, core_spirits=current_spirits())
    )
    assert first_probe.invalid_reason is None
    assert second_probe.invalid_reason is None
    assert sum(
        record.association == "other-controlled-cast"
        for record in first_probe.event_records
    ) == 1
    assert sum(
        record.event_type == "SKILL_FINISHED"
        and record.association == "active-controlled-cast"
        for record in second_probe.event_records
    ) == 1

    controller._observe_armor_deployment(
        _snapshot(tick_ms=2300, core_spirits=current_spirits())
    )
    assert first_probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert first_skill in controller._armor_deployment_epoch.tokens

    controller._observe_armor_deployment(
        _snapshot(tick_ms=3250, core_spirits=current_spirits())
    )
    assert second_probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert set(controller._armor_deployment_epoch.tokens) == {
        first_skill,
        second_skill,
    }
    return controller, first_probe, second_probe


def test_shelter_union_overlapping_probes_both_issue_tokens(
    monkeypatch: Any,
) -> None:
    _exercise_overlapping_deployment_pair(
        monkeypatch,
        first_skill=ST.Shelter_ID,
        second_skill=ST.Union_ID,
    )


def test_union_displacement_overlapping_probes_both_issue_tokens(
    monkeypatch: Any,
) -> None:
    _exercise_overlapping_deployment_pair(
        monkeypatch,
        first_skill=ST.Union_ID,
        second_skill=ST.Displacement_ID,
    )


def test_newer_terminal_after_settle_deadline_does_not_preempt_candidate_update(
    monkeypatch: Any,
) -> None:
    controller, events, shelter_probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    union_pre_existing = _observation(ST.Union_ID, agent_id=20)
    union_probe = controller._record_armor_deployment_request(
        ST.Union_ID,
        _snapshot(
            tick_ms=1700,
            core_spirits={
                ST.Shelter_ID: shelter_spirits,
                ST.Union_ID: (union_pre_existing,),
            },
        ),
    )
    assert union_probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=ST.Union_ID,
        packet_at=1800,
        activation_at=1810,
        finish_at=2400,
    )
    union_candidate = _observation(
        ST.Union_ID,
        agent_id=21,
        position=(10.0, 0.0),
    )
    core_spirits = {
        ST.Shelter_ID: shelter_spirits,
        ST.Union_ID: (union_pre_existing, union_candidate),
    }

    # The first observation after Shelter's deadline processes Union's finish first.
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2600, core_spirits=core_spirits)
    )
    assert shelter_probe.settle_until_ms == 2300
    assert shelter_probe.invalid_reason is None
    assert shelter_probe.token_issued
    assert union_probe.finish_at_ms == 2400
    assert controller._armor_deployment_epoch is not None
    assert ST.Shelter_ID in controller._armor_deployment_epoch.tokens

    controller._observe_armor_deployment(
        _snapshot(tick_ms=3600, core_spirits=core_spirits)
    )
    assert union_probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert set(controller._armor_deployment_epoch.tokens) == {
        ST.Shelter_ID,
        ST.Union_ID,
    }


def test_newer_same_snapshot_duplicate_rejects_only_its_own_probe(
    monkeypatch: Any,
) -> None:
    controller, events, shelter_probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    union_pre_existing = _observation(ST.Union_ID, agent_id=20)
    union_probe = controller._record_armor_deployment_request(
        ST.Union_ID,
        _snapshot(
            tick_ms=1700,
            core_spirits={
                ST.Shelter_ID: shelter_spirits,
                ST.Union_ID: (union_pre_existing,),
            },
        ),
    )
    assert union_probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=ST.Union_ID,
        packet_at=1800,
        activation_at=1810,
        finish_at=2200,
        terminal_occurrences=2,
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=2250,
            core_spirits={
                ST.Shelter_ID: shelter_spirits,
                ST.Union_ID: (union_pre_existing,),
            },
        )
    )
    assert union_probe.invalid_reason == "duplicate_terminal_in_snapshot"
    assert shelter_probe.invalid_reason is None
    assert any(
        record.association == "other-controlled-cast"
        for record in shelter_probe.event_records
    )

    controller._observe_armor_deployment(
        _snapshot(tick_ms=2300, core_spirits={ST.Shelter_ID: shelter_spirits})
    )
    assert shelter_probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert set(controller._armor_deployment_epoch.tokens) == {ST.Shelter_ID}


def test_distinct_second_terminal_for_same_cast_still_rejects_probe(
    monkeypatch: Any,
) -> None:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=ST.Shelter_ID,
        packet_at=1100,
        activation_at=1110,
        finish_at=1200,
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1200, core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)})
    )
    assert probe.finish_at_ms == 1200

    events.append(
        _raw_event(
            timestamp=1250,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        )
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1250, core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)})
    )
    assert probe.invalid_reason == "conflicting_or_duplicate_terminal"
    assert controller._armor_deployment_epoch is None


def test_retiring_last_terminal_owner_clears_it_before_later_raw_zero(
    monkeypatch: Any,
) -> None:
    controller, events, retired_probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    assert controller._armor_deployment_last_terminal_cast is retired_probe

    controller._invalidate_armor_deployment_probe(
        retired_probe,
        reason="regression_retirement",
    )
    assert retired_probe.invalid_reason == "regression_retirement"
    assert retired_probe not in controller._armor_deployment_probes.values()
    assert controller._armor_deployment_last_terminal_cast is None

    union_pre_existing = _observation(ST.Union_ID, agent_id=20)
    pending_probe = controller._record_armor_deployment_request(
        ST.Union_ID,
        _snapshot(
            tick_ms=1400,
            core_spirits={
                ST.Shelter_ID: shelter_spirits,
                ST.Union_ID: (union_pre_existing,),
            },
        ),
    )
    assert pending_probe is not None
    later_terminal = _raw_event(
        timestamp=1500,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
        agent_id=23,
        skill_id=0,
    )
    events.append(later_terminal)
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1500,
            core_spirits={ST.Union_ID: (union_pre_existing,)},
        )
    )
    assert controller._armor_deployment_last_terminal_cast is None
    assert pending_probe.finish_at_ms is None
    assert controller._deployment_event_key(later_terminal) not in pending_probe.seen_event_keys
    assert len(retired_probe.event_records) == 3


def test_candidate_disappearance_retires_last_terminal_owner(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    assert controller._armor_deployment_last_terminal_cast is probe

    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1400,
            core_spirits={ST.Shelter_ID: (shelter_spirits[0],)},
        )
    )
    assert probe.invalid_reason == "candidate_disappeared"
    assert probe not in controller._armor_deployment_probes.values()
    assert controller._armor_deployment_last_terminal_cast is None


def test_same_skill_replacement_clears_retired_terminal_owner(
    monkeypatch: Any,
) -> None:
    controller, events, old_probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    assert controller._armor_deployment_last_terminal_cast is old_probe
    old_record_count = len(old_probe.event_records)

    replacement = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1400,
            core_spirits={ST.Shelter_ID: shelter_spirits},
        ),
    )
    assert replacement is not None
    assert old_probe.invalid_reason == "replacement_deployment_requested"
    assert controller._armor_deployment_probes[ST.Shelter_ID] is replacement
    assert controller._armor_deployment_last_terminal_cast is None

    later_terminal = _raw_event(
        timestamp=1500,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
        agent_id=23,
        skill_id=0,
    )
    events.append(later_terminal)
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1500, core_spirits={ST.Shelter_ID: shelter_spirits})
    )
    assert replacement.finish_at_ms is None
    assert controller._deployment_event_key(later_terminal) not in replacement.seen_event_keys
    assert len(old_probe.event_records) == old_record_count
    assert controller._armor_deployment_last_terminal_cast is None


def test_raw_zero_fallback_discards_retired_terminal_owner_reference(
    monkeypatch: Any,
) -> None:
    controller, events, retired_probe, shelter_spirits = (
        _start_candidate_settling_probe(monkeypatch, ST.Shelter_ID)
    )
    controller._invalidate_armor_deployment_probe(
        retired_probe,
        reason="regression_retirement",
    )
    assert controller._armor_deployment_last_terminal_cast is None

    union_pre_existing = _observation(ST.Union_ID, agent_id=20)
    pending_probe = controller._record_armor_deployment_request(
        ST.Union_ID,
        _snapshot(
            tick_ms=1400,
            core_spirits={
                ST.Shelter_ID: shelter_spirits,
                ST.Union_ID: (union_pre_existing,),
            },
        ),
    )
    assert pending_probe is not None

    # Simulate stale state to exercise the defensive consumption check.
    controller._armor_deployment_last_terminal_cast = retired_probe
    later_terminal = _raw_event(
        timestamp=1500,
        event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
        agent_id=23,
        skill_id=0,
    )
    events.append(later_terminal)
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1500,
            core_spirits={ST.Union_ID: (union_pre_existing,)},
        )
    )
    assert controller._armor_deployment_last_terminal_cast is None
    assert pending_probe.finish_at_ms is None
    assert controller._deployment_event_key(later_terminal) not in pending_probe.seen_event_keys
    assert len(retired_probe.event_records) == 3


def test_late_replacement_probe_cannot_reuse_old_event(monkeypatch: Any) -> None:
    events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    first = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert first is not None
    controller._observe_armor_deployment(_snapshot(tick_ms=1200))
    second = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=2000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert second is not None
    controller._observe_armor_deployment(_snapshot(tick_ms=3200))
    assert second.activation_at_ms is None
    assert second.finish_at_ms is None


def test_request_baseline_fences_future_timestamped_buffered_events(
    monkeypatch: Any,
) -> None:
    events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    assert len(probe.baseline_event_keys) == 3

    core_spirits = {
        ST.Shelter_ID: (
            _observation(ST.Shelter_ID, agent_id=10),
            _observation(ST.Shelter_ID, agent_id=11),
        )
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1300, core_spirits=core_spirits)
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2300, core_spirits=core_spirits)
    )
    assert not probe.seen_event_keys
    assert probe.finish_at_ms is None
    assert probe.invalid_reason == "activation_sequence_missing_or_late"
    assert controller._armor_deployment_epoch is None


def test_foreign_baseline_activation_still_invalidates_probe(
    monkeypatch: Any,
) -> None:
    events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=24,
            skill_id=ST.Shelter_ID,
        )
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(
        [
            _raw_event(
                timestamp=1300,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1310,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1400,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=0,
            ),
        ]
    )
    core_spirits = {
        ST.Shelter_ID: (
            _observation(ST.Shelter_ID, agent_id=10),
            _observation(ST.Shelter_ID, agent_id=11),
        )
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1500, core_spirits=core_spirits)
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2500, core_spirits=core_spirits)
    )
    assert probe.invalid_reason == "foreign_expected_skill_activation"
    assert probe.foreign_event_casters == {24}
    assert controller._armor_deployment_epoch is None


def test_post_baseline_events_can_still_issue_a_token(monkeypatch: Any) -> None:
    events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(
        [
            _raw_event(
                timestamp=1300,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1310,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1400,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=0,
            ),
        ]
    )
    core_spirits = {
        ST.Shelter_ID: (
            _observation(ST.Shelter_ID, agent_id=10),
            _observation(ST.Shelter_ID, agent_id=11),
        )
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=1500, core_spirits=core_spirits)
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2500, core_spirits=core_spirits)
    )
    assert controller._armor_deployment_epoch is not None
    assert controller._armor_deployment_epoch.tokens[ST.Shelter_ID].witness_agent_id == 11


def test_later_probe_is_not_poisoned_by_prior_baseline_bookkeeping(
    monkeypatch: Any,
) -> None:
    events = [
        _raw_event(
            timestamp=1100,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1110,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=23,
            skill_id=ST.Shelter_ID,
        ),
        _raw_event(
            timestamp=1200,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
            agent_id=23,
            skill_id=0,
        ),
    ]
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    first = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert first is not None
    second = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=2000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert second is not None
    assert first.invalid_reason == "replacement_deployment_requested"
    events.extend(
        [
            _raw_event(
                timestamp=2100,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=2110,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=2200,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=0,
            ),
        ]
    )
    core_spirits = {
        ST.Shelter_ID: (
            _observation(ST.Shelter_ID, agent_id=10),
            _observation(ST.Shelter_ID, agent_id=11),
        )
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=2200, core_spirits=core_spirits)
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=3300, core_spirits=core_spirits)
    )
    assert controller._armor_deployment_epoch is not None
    assert second.seen_event_keys


def test_unspawned_candidate_settles_from_spawn_transition_and_second_is_ambiguous(
    monkeypatch: Any,
) -> None:
    controller = _production_controller()
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(
        [
            _raw_event(
                timestamp=1100,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1110,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1200,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=0,
            ),
        ]
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1300,
            core_spirits={
                ST.Shelter_ID: (
                    _observation(ST.Shelter_ID, agent_id=11, spawned=False),
                )
            },
        )
    )
    assert probe.candidates[11].first_spawned_at_ms is None
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1800,
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=11),)
            },
        )
    )
    assert probe.qualifying_at_ms == 1800
    assert probe.settle_until_ms == 2800
    assert probe.candidates[11].spawned_evidence_checked
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=2500,
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=11),)
            },
        )
    )
    assert controller._armor_deployment_epoch is None
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=2800,
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=11),)
            },
        )
    )
    assert controller._armor_deployment_epoch is not None

    controller = _production_controller()
    events = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1100,
            core_spirits={
                ST.Shelter_ID: (
                    _observation(ST.Shelter_ID, agent_id=11),
                    _observation(ST.Shelter_ID, agent_id=12),
                )
            },
        )
    )
    assert probe.invalid_reason == "multiple_new_same_model_candidates"


def test_association_radius_and_preexisting_ids_fail_closed(monkeypatch: Any) -> None:
    controller = _production_controller()
    events: list[Any] = []
    _complete_deployment(
        controller,
        monkeypatch,
        events,
        skill_id=ST.Shelter_ID,
        request_at=1000,
        packet_at=1100,
        activation_at=1110,
        finish_at=1200,
        candidate_at=1300,
        settle_at=2300,
        candidate_position=(128.0, 0.0),
    )
    assert controller._armor_deployment_epoch is not None

    controller = _production_controller()
    events = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    events.extend(
        [
            _raw_event(
                timestamp=1100,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1110,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                agent_id=23,
                skill_id=ST.Shelter_ID,
            ),
            _raw_event(
                timestamp=1200,
                event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                agent_id=23,
                skill_id=0,
            ),
        ]
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=1300,
            core_spirits={
                ST.Shelter_ID: (
                    _observation(ST.Shelter_ID, agent_id=10),
                    _observation(ST.Shelter_ID, agent_id=12, position=(129.0, 0.0)),
                )
            },
        )
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=3201,
            core_spirits={
                ST.Shelter_ID: (
                    _observation(ST.Shelter_ID, agent_id=10),
                    _observation(ST.Shelter_ID, agent_id=12, position=(129.0, 0.0)),
                )
            },
        )
    )
    assert probe.invalid_reason == "candidate_out_of_association_radius"


def test_finish_to_candidate_deadline_is_checked_before_qualification(
    monkeypatch: Any,
) -> None:
    for candidate_at, expected_epoch in ((3200, True), (3201, False)):
        controller = _production_controller()
        events: list[Any] = []
        probe = _complete_deployment(
            controller,
            monkeypatch,
            events,
            skill_id=ST.Shelter_ID,
            request_at=1000,
            packet_at=1100,
            activation_at=1110,
            finish_at=1200,
            candidate_at=candidate_at,
            settle_at=candidate_at + ST.ARMOR_CANDIDATE_SETTLE_MS,
        )
        assert (controller._armor_deployment_epoch is not None) is expected_epoch
        if expected_epoch:
            assert probe.invalid_reason is None
        else:
            assert probe.invalid_reason == "candidate_missing_or_late"


def test_qualified_candidate_issues_after_request_window_by_one_ms(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    assert probe.requested_at_ms == 1000
    assert probe.finish_at_ms == 2750
    assert probe.settle_until_ms == 5750
    assert not probe.token_issued

    controller._observe_armor_deployment(
        _snapshot(tick_ms=5751, core_spirits=spirits)
    )

    assert probe.invalid_reason is None
    assert probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert ST.Shelter_ID in controller._armor_deployment_epoch.tokens


def test_qualified_candidate_issues_on_first_observer_well_after_settlement(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    candidate = spirits[ST.Shelter_ID][1]
    qualification_fingerprint = probe.candidates[11].qualification_fingerprint
    assert qualification_fingerprint == ST.My_Soul_Twisting._armor_witness_fingerprint(
        candidate
    )
    observer_at = 8000
    assert observer_at > probe.settle_until_ms + ST.ARMOR_CANDIDATE_SETTLE_MS

    controller._observe_armor_deployment(
        _snapshot(tick_ms=observer_at, core_spirits=spirits)
    )

    assert probe.invalid_reason is None
    assert probe.token_issued
    assert controller._armor_deployment_epoch is not None
    assert ST.Shelter_ID in controller._armor_deployment_epoch.tokens
    assert controller._armor_deployment_epoch.started_at_ms == 2750
    assert controller._armor_deployment_epoch.expires_at_ms == 17750
    assert (
        controller._armor_deployment_epoch.tokens[
            ST.Shelter_ID
        ].witness_fingerprint
        == qualification_fingerprint
    )


def test_delayed_first_token_obeys_finish_based_epoch_expiry_boundary(
    monkeypatch: Any,
) -> None:
    for observer_at, should_issue in (
        (17749, True),
        (17750, False),
        (17751, False),
    ):
        controller, _events, probe, spirits = _start_qualified_candidate_probe(
            monkeypatch
        )
        controller._observe_armor_deployment(
            _snapshot(tick_ms=observer_at, core_spirits=spirits)
        )

        assert probe.token_issued is should_issue
        if should_issue:
            epoch = controller._armor_deployment_epoch
            assert epoch is not None
            assert epoch.started_at_ms == 2750
            assert epoch.expires_at_ms == 17750
            assert probe.invalid_reason is None
        else:
            assert probe.invalid_reason == "deployment_epoch_expired_before_token"
            assert controller._armor_deployment_epoch is None


def test_expired_epoch_rejects_old_delayed_evidence_and_cleans_up(
    monkeypatch: Any,
) -> None:
    union_witness = _observation(ST.Union_ID, agent_id=100)
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch,
        retained_core_spirits={ST.Union_ID: (union_witness,)},
    )
    expired_epoch = _seed_epoch(
        controller,
        token_skills=(ST.Union_ID,),
        finish_at=-9000,
        expires_at=6000,
    )
    controller._armor_deployment_epoch_counter = expired_epoch.epoch_id

    controller._observe_armor_deployment(
        _snapshot(tick_ms=8000, core_spirits=spirits)
    )

    assert probe.invalid_reason == "deployment_epoch_expired_before_token"
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is expired_epoch
    assert expired_epoch.expires_at_ms == 6000
    assert set(expired_epoch.tokens) == {ST.Union_ID}
    assert ST.Shelter_ID not in expired_epoch.tokens

    eligible, _token_types, reason = controller._armor_eligibility(
        _snapshot(tick_ms=8000, core_spirits=spirits)
    )
    assert not eligible
    assert reason == "deployment_epoch_expired"
    assert controller._armor_deployment_epoch is None


def test_finish_after_expired_epoch_starts_new_non_sliding_epoch(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch,
        request_at=2250,
        packet_at=2450,
        activation_at=2500,
        finish_at=4000,
        candidate_at=6000,
    )
    expired_epoch = _seed_epoch(
        controller,
        token_skills=(ST.Union_ID,),
        finish_at=-12000,
        expires_at=3000,
    )
    controller._armor_deployment_epoch_counter = expired_epoch.epoch_id

    controller._observe_armor_deployment(
        _snapshot(tick_ms=8000, core_spirits=spirits)
    )

    epoch = controller._armor_deployment_epoch
    assert epoch is not None
    assert epoch is not expired_epoch
    assert probe.token_issued
    assert epoch.started_at_ms == 4000
    assert epoch.expires_at_ms == 19000
    assert set(epoch.tokens) == {ST.Shelter_ID}


def test_unqualified_probe_still_expires_at_request_window(
    monkeypatch: Any,
) -> None:
    events: list[Any] = []
    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
    controller = _production_controller()
    pre_existing = _observation(ST.Shelter_ID, agent_id=10)
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (pre_existing,)},
        ),
    )
    assert probe is not None
    _append_controlled_ritual_events(
        events,
        skill_id=ST.Shelter_ID,
        packet_at=1200,
        activation_at=1250,
        finish_at=2750,
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=2750,
            core_spirits={ST.Shelter_ID: (pre_existing,)},
        )
    )

    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=5751,
            core_spirits={ST.Shelter_ID: (pre_existing,)},
        )
    )

    assert probe.qualifying_at_ms is None
    assert probe.invalid_reason == "deployment_probe_window_expired"
    assert controller._armor_deployment_epoch is None


def test_qualified_candidate_disappearance_rejects_delayed_token(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    controller._observe_armor_deployment(
        _snapshot(
            tick_ms=8000,
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)
            },
        )
    )

    assert probe.invalid_reason == "candidate_disappeared"
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None

    controller._observe_armor_deployment(
        _snapshot(tick_ms=9000, core_spirits=spirits)
    )
    assert probe.invalid_reason == "candidate_disappeared"
    assert probe not in controller._armor_deployment_probes.values()
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None


def test_same_agent_with_changed_valid_root_breaks_qualification_identity(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    changed_candidate = _observation(
        ST.Shelter_ID,
        agent_id=11,
        owner_id=45,
        root_category=ST._SpiritCategory.PARTY_ROOT_MATCH,
        position=(10.0, 0.0),
    )
    changed_spirits = {
        ST.Shelter_ID: (spirits[ST.Shelter_ID][0], changed_candidate)
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=8000, core_spirits=changed_spirits)
    )

    assert probe.invalid_reason == "candidate_identity_changed"
    assert probe.candidates[11].qualification_fingerprint == (100, 12, "party-root-match")
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None


def test_qualification_identity_guard_preserves_other_candidate_rejections(
    monkeypatch: Any,
) -> None:
    for mismatch, expected_reason in (
        ("model", "candidate_disappeared"),
        ("root", "candidate_qualification_lost"),
        ("dead", "candidate_qualification_lost"),
        ("despawned", "candidate_qualification_lost"),
    ):
        controller, _events, probe, spirits = _start_qualified_candidate_probe(
            monkeypatch
        )
        original_candidate = spirits[ST.Shelter_ID][1]
        if mismatch == "model":
            changed_candidate = replace(
                original_candidate,
                model_id=original_candidate.model_id + 1,
            )
        elif mismatch == "root":
            changed_candidate = _observation(
                ST.Shelter_ID,
                agent_id=11,
                root_category=ST._SpiritCategory.UNKNOWN,
                position=(10.0, 0.0),
            )
        elif mismatch == "dead":
            changed_candidate = _observation(
                ST.Shelter_ID,
                agent_id=11,
                alive=False,
                position=(10.0, 0.0),
            )
        else:
            changed_candidate = _observation(
                ST.Shelter_ID,
                agent_id=11,
                spawned=False,
                position=(10.0, 0.0),
            )
        changed_spirits = {
            ST.Shelter_ID: (spirits[ST.Shelter_ID][0], changed_candidate)
        }
        controller._observe_armor_deployment(
            _snapshot(tick_ms=8000, core_spirits=changed_spirits)
        )

        assert probe.invalid_reason == expected_reason
        assert not probe.token_issued
        assert controller._armor_deployment_epoch is None


def test_second_candidate_during_delayed_settlement_rejects_token(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    delayed_spirits = {
        ST.Shelter_ID: (
            *spirits[ST.Shelter_ID],
            _observation(
                ST.Shelter_ID,
                agent_id=12,
                position=(20.0, 0.0),
            ),
        )
    }
    controller._observe_armor_deployment(
        _snapshot(tick_ms=8000, core_spirits=delayed_spirits)
    )

    assert probe.invalid_reason == "multiple_new_same_model_candidates"
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None


def test_foreign_same_skill_activation_blocks_delayed_token(
    monkeypatch: Any,
) -> None:
    controller, events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    events.append(
        _raw_event(
            timestamp=6000,
            event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
            agent_id=24,
            skill_id=ST.Shelter_ID,
        )
    )
    controller._observe_armor_deployment(
        _snapshot(tick_ms=8000, core_spirits=spirits)
    )

    assert probe.invalid_reason == "foreign_expected_skill_activation"
    assert probe.foreign_event_casters == {24}
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None


def test_lifecycle_reset_before_delayed_token_discards_probe(
    monkeypatch: Any,
) -> None:
    controller, _events, probe, spirits = _start_qualified_candidate_probe(
        monkeypatch
    )
    controller._observe_armor_deployment(
        _snapshot(
            map_id=43,
            instance_uptime_ms=1000,
            tick_ms=8000,
            core_spirits=spirits,
        )
    )
    controller._observe_armor_deployment(
        _snapshot(
            map_id=43,
            instance_uptime_ms=1000,
            tick_ms=9000,
            core_spirits=spirits,
        )
    )

    assert probe.invalid_reason == "map_or_instance_changed"
    assert probe not in controller._armor_deployment_probes.values()
    assert not probe.token_issued
    assert controller._armor_deployment_epoch is None


def test_spawned_candidate_bad_position_cannot_recover(
    monkeypatch: Any,
) -> None:
    def run_case(
        first_position: tuple[float, float] | None,
        later_position: tuple[float, float],
    ) -> tuple[Any, Any]:
        controller = _production_controller()
        events: list[Any] = []
        monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: list(events))
        probe = controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=1000,
                core_spirits={
                    ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)
                },
            ),
        )
        assert probe is not None
        events.extend(
            [
                _raw_event(
                    timestamp=1100,
                    event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATE_PACKET,
                    agent_id=23,
                    skill_id=ST.Shelter_ID,
                ),
                _raw_event(
                    timestamp=1110,
                    event_type=ST.PyAgentEvents.PyEventType.SKILL_ACTIVATED,
                    agent_id=23,
                    skill_id=ST.Shelter_ID,
                ),
                _raw_event(
                    timestamp=1200,
                    event_type=ST.PyAgentEvents.PyEventType.SKILL_FINISHED,
                    agent_id=23,
                    skill_id=0,
                ),
            ]
        )
        controller._observe_armor_deployment(
            _snapshot(
                tick_ms=1300,
                core_spirits={
                    ST.Shelter_ID: (
                        _observation(ST.Shelter_ID, agent_id=10),
                        _observation(
                            ST.Shelter_ID,
                            agent_id=11,
                            position=first_position,
                        ),
                    )
                },
            )
        )
        controller._observe_armor_deployment(
            _snapshot(
                tick_ms=1400,
                core_spirits={
                    ST.Shelter_ID: (
                        _observation(ST.Shelter_ID, agent_id=10),
                        _observation(
                            ST.Shelter_ID,
                            agent_id=11,
                            position=later_position,
                        ),
                    )
                },
            )
        )
        return probe, controller

    missing_position_probe, missing_position_controller = run_case(
        None, (10.0, 0.0)
    )
    assert missing_position_probe.invalid_reason == "candidate_position_unreadable"
    assert missing_position_controller._armor_deployment_epoch is None

    outside_radius_probe, outside_radius_controller = run_case(
        (129.0, 0.0), (10.0, 0.0)
    )
    assert (
        outside_radius_probe.invalid_reason
        == "candidate_out_of_association_radius"
    )
    assert outside_radius_controller._armor_deployment_epoch is None


def test_timing_boundaries_use_inclusive_limits() -> None:
    controller = _production_controller()
    probe = ST._ArmorDeploymentProbe(
        skill_id=ST.Shelter_ID,
        model_id=ST._CORE_MODEL_BY_SKILL[ST.Shelter_ID],
        requested_at_ms=1000,
        map_id=42,
        instance_uptime_ms=5000,
        player_agent_id=23,
        cast_origin=(0.0, 0.0),
        pre_agent_ids=frozenset(),
        activate_packet_at_ms=1500,
        activation_at_ms=1500,
        finish_at_ms=2500,
    )
    controller._armor_deployment_probes = {ST.Shelter_ID: probe}
    controller._check_deployment_probe_timing(probe, 2500)
    assert probe.invalid_reason is None
    probe.finish_at_ms = 3001
    controller._check_deployment_probe_timing(probe, 2501)
    assert probe.invalid_reason == "finish_out_of_bounds"

    probe = ST._ArmorDeploymentProbe(
        skill_id=ST.Shelter_ID,
        model_id=ST._CORE_MODEL_BY_SKILL[ST.Shelter_ID],
        requested_at_ms=1000,
        map_id=42,
        instance_uptime_ms=5000,
        player_agent_id=23,
        cast_origin=(0.0, 0.0),
        pre_agent_ids=frozenset(),
    )
    controller._armor_deployment_probes = {ST.Shelter_ID: probe}
    controller._check_deployment_probe_timing(
        probe, 1000 + ST.ARMOR_REQUEST_TO_ACTIVATION_MS
    )
    assert probe.invalid_reason is None
    controller._check_deployment_probe_timing(
        probe, 1000 + ST.ARMOR_REQUEST_TO_ACTIVATION_MS + 1
    )
    assert probe.invalid_reason == "activation_sequence_missing_or_late"


def test_event_read_failure_and_lifecycle_reset_fail_closed(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        ST.PyAgentEvents,
        "peek_events",
        lambda: (_ for _ in ()).throw(RuntimeError("read failed")),
    )
    controller = _production_controller()
    assert (
        controller._record_armor_deployment_request(
            ST.Shelter_ID,
            _snapshot(
                tick_ms=1000,
                core_spirits={
                    ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)
                },
            ),
        )
        is None
    )

    monkeypatch.setattr(ST.PyAgentEvents, "peek_events", lambda: [])
    controller = _production_controller()
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=1000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=10),)},
        ),
    )
    assert probe is not None
    controller._observe_armor_deployment(
        _snapshot(map_id=43, instance_uptime_ms=1000, tick_ms=1100)
    )
    assert probe.invalid_reason == "map_or_instance_changed"


def test_witness_invalidates_and_never_resurrects() -> None:
    controller = _production_controller()
    _seed_epoch(controller)
    controller._observe_armor_deployment(
        _snapshot(
            core_spirits={
                ST.Shelter_ID: (),
                ST.Union_ID: (_observation(ST.Union_ID, agent_id=101),),
                ST.Displacement_ID: (
                    _observation(ST.Displacement_ID, agent_id=30),
                ),
            }
        )
    )
    assert controller._armor_deployment_epoch is not None
    assert ST.Shelter_ID not in controller._armor_deployment_epoch.tokens
    assert controller._armor_qualifying_core_types(_full_core_snapshot()) == (
        ST.Union_ID,
    )


def test_witness_fingerprint_change_invalidates_without_substitution() -> None:
    controller = _production_controller()
    _seed_epoch(controller)
    changed = _full_core_snapshot()
    changed.core_spirits[ST.Shelter_ID] = (
        _observation(
            ST.Shelter_ID,
            agent_id=100,
            root_category=ST._SpiritCategory.UNKNOWN,
        ),
    )
    controller._observe_armor_deployment(changed)
    assert controller._armor_deployment_epoch is not None
    assert ST.Shelter_ID not in controller._armor_deployment_epoch.tokens


def test_epoch_resets_on_player_change_loading_nonexplorable_and_death() -> None:
    for overrides in (
        {"player_agent_id": 24},
        {"map_loading": True},
        {"map_explorable": False},
        {"player_alive": False},
    ):
        controller = _production_controller()
        _seed_epoch(controller)
        controller._observe_armor_deployment(_snapshot(**overrides))
        assert controller._armor_deployment_epoch is None


def test_two_real_tokens_join_one_non_sliding_epoch(monkeypatch: Any) -> None:
    controller = _production_controller()
    events: list[Any] = []
    _complete_deployment(
        controller,
        monkeypatch,
        events,
        skill_id=ST.Shelter_ID,
        request_at=1000,
        packet_at=1100,
        activation_at=1200,
        finish_at=1500,
        candidate_at=1600,
        settle_at=2600,
    )
    assert controller._armor_deployment_epoch is not None
    expiry = controller._armor_deployment_epoch.expires_at_ms
    _complete_deployment(
        controller,
        monkeypatch,
        events,
        skill_id=ST.Union_ID,
        request_at=4000,
        packet_at=4100,
        activation_at=4200,
        finish_at=4500,
        candidate_at=4600,
        settle_at=5600,
        pre_agent_id=20,
        candidate_id=21,
        retained_core_spirits={
            ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=11),)
        },
    )
    assert controller._armor_deployment_epoch is not None
    assert set(controller._armor_deployment_epoch.tokens) == {
        ST.Shelter_ID,
        ST.Union_ID,
    }
    assert controller._armor_deployment_epoch.expires_at_ms == expiry


def test_threshold_epoch_movement_and_final_revalidation() -> None:
    controller = _production_controller()
    snapshot = _full_core_snapshot()
    _seed_epoch(controller, token_skills=(ST.Shelter_ID,))
    assert not controller._armor_eligibility(snapshot)[0]
    _seed_epoch(controller, token_skills=(ST.Shelter_ID, ST.Union_ID))
    assert controller._armor_eligibility(snapshot)[0]

    moved = _full_core_snapshot(tick_ms=3000, player_position=(1100.0, 0.0))
    assert not controller._armor_eligibility(moved)[0]
    assert controller._armor_deployment_epoch is not None
    assert controller._armor_eligibility(_full_core_snapshot(tick_ms=4000))[0]

    invalid = _full_core_snapshot(player_position=(2000.0, 0.0))
    action = ST._SoulTwistingAction(
        kind=ST._ActionKind.POST_DEPLOYMENT,
        skill_id=ST.Armor_of_Unfeeling_ID,
        target_agent_id=0,
    )
    valid, reason = controller._revalidate_action(action, invalid)
    assert not valid
    assert reason == "deployment_witness_out_of_earshot"
    assert controller._armor_deployment_epoch is not None


def test_epoch_is_non_sliding_and_expires_at_fifteen_seconds() -> None:
    controller = _production_controller()
    epoch = _seed_epoch(controller, finish_at=1000)
    assert epoch.expires_at_ms == 1000 + ST.ARMOR_DEPLOYMENT_EPOCH_MS
    assert not controller._armor_eligibility(
        _full_core_snapshot(tick_ms=epoch.expires_at_ms)
    )[0]
    assert controller._armor_deployment_epoch is None


def test_same_skill_replacement_retires_old_token_without_extending_epoch() -> None:
    controller = _production_controller()
    epoch = _seed_epoch(controller, finish_at=1000)
    probe = controller._record_armor_deployment_request(
        ST.Shelter_ID,
        _snapshot(
            tick_ms=4000,
            core_spirits={ST.Shelter_ID: (_observation(ST.Shelter_ID, agent_id=100),)},
        ),
    )
    assert probe is not None
    assert ST.Shelter_ID not in epoch.tokens
    assert ST.Union_ID in epoch.tokens
    assert controller._armor_deployment_epoch is epoch


def test_armor_is_targetless_and_epoch_consumes_once() -> None:
    controller = _production_controller()
    _seed_epoch(controller)
    snapshot = _full_core_snapshot()
    assert controller._consume_armor_deployment_epoch(snapshot)
    assert controller._armor_deployment_epoch is None
    assert not controller._consume_armor_deployment_epoch(snapshot)

    calls: list[dict[str, Any]] = []

    def armor_cast(**kwargs: Any) -> Any:
        calls.append(kwargs)
        yield
        return True

    controller.CastSkillID = armor_cast
    action = ST._SoulTwistingAction(
        kind=ST._ActionKind.POST_DEPLOYMENT,
        skill_id=ST.Armor_of_Unfeeling_ID,
        target_agent_id=0,
    )
    assert _finish_generator(controller._execute_action(action)) is True
    assert calls[0]["target_agent_id"] == 0


def test_phase1_and_phase2a_paths_remain_intact() -> None:
    controller = _controller()
    missing = controller._select_action(
        _snapshot(
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=True),)
            }
        )
    )
    assert missing.kind is ST._ActionKind.CORE_DEPLOYMENT
    assert missing.skill_id == ST.Union_ID

    moving = controller._select_action(
        _snapshot(
            player_moving=True,
            core_spirits={
                ST.Shelter_ID: (_observation(ST.Shelter_ID, covers=False),)
            },
        )
    )
    assert moving.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert moving.reason == "movement_debounce_Shelter"
