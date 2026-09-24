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
        ),
        Routines=SimpleNamespace(),
        SpiritModelID=_SpiritModelID,
        ThrottledTimer=_ThrottledTimer,
        Utils=SimpleNamespace(),
    )
    corelib.__path__ = []
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
    position: tuple[float, float] = (0.0, 0.0),
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
    assert not hasattr(ST, "PyAgentEvents")
    assert not any(name.startswith("_Owner") for name in vars(ST))
    assert not any("learned" in name for name in vars(first))
    assert not any("learned" in name for name in vars(second))


def test_summon_is_excluded_from_core_policy_actions() -> None:
    controller = _controller(equipped={ST.Summon_Spirits_kurzick_ID})
    action = controller._select_action(_snapshot(core_spirits={}))
    assert action.kind is ST._ActionKind.BLOCKED_NO_ACTION
    assert action.skill_id == 0


def test_armor_is_selected_only_after_functional_core_package_is_online() -> None:
    equipped = set(ST._CORE_SKILLS) | {ST.Armor_of_Unfeeling_ID}
    controller = _controller(equipped=equipped)
    controller.CanCastSkillID = lambda skill_id: skill_id == ST.Armor_of_Unfeeling_ID
    snapshot = _snapshot(
        core_spirits={
            skill_id: (_observation(skill_id, agent_id=skill_id),)
            for skill_id in ST._CORE_SKILLS
        }
    )
    action = controller._select_action(snapshot)
    assert action.kind is ST._ActionKind.POST_DEPLOYMENT
    assert action.skill_id == ST.Armor_of_Unfeeling_ID


def test_armor_execution_still_delegates_to_shared_communing_path() -> None:
    controller = _controller(equipped={ST.Armor_of_Unfeeling_ID})

    def armor_cast() -> Any:
        yield
        return True

    controller.skills = SimpleNamespace(
        Ritualist=SimpleNamespace(
            Communing=SimpleNamespace(Armor_of_Unfeeling=armor_cast)
        )
    )
    action = ST._SoulTwistingAction(
        kind=ST._ActionKind.POST_DEPLOYMENT,
        skill_id=ST.Armor_of_Unfeeling_ID,
    )
    assert _finish_generator(controller._execute_action(action)) is True


def test_diagnostics_report_functional_coverage_without_temporary_identity_events(
    monkeypatch: Any,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        ST.PySystem.Console,
        "Log",
        lambda _channel, message, _message_type: messages.append(message),
        raising=False,
    )
    controller = _controller()
    snapshot = _snapshot(
        core_spirits={
            ST.Shelter_ID: (_observation(ST.Shelter_ID),),
        }
    )
    controller._emit_snapshot_diagnostics(snapshot, phase="test")
    joined = "\n".join(messages)
    assert "event=core" in joined
    assert "functional_covers" in joined
    assert "local_native_root_id" in joined
    assert "owner-identity" not in joined
    assert "owner-skill-event" not in joined
    assert "spirit-identity" not in joined
