# pyright: reportMissingImports=false
"""Offline regressions for profile-aware hex-priority caching."""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _HexRuntime:
    priority: Any
    config: Any
    active_identity: list[str]
    profile_loads: list[tuple[str, str]]
    profile_states: dict[tuple[str, str], Any]
    skill_id_calls: list[str]
    hex_name: str
    professions: dict[int, int]
    effect_scan_calls: list[int]


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _install_package(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = _install_module(monkeypatch, name)
    module.__path__ = []
    return module


def _load_source(monkeypatch: pytest.MonkeyPatch, name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load production source at {path}")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hex_runtime(monkeypatch: pytest.MonkeyPatch) -> _HexRuntime:
    for package_name in (
        "Py4GWCoreLib",
        "Py4GWCoreLib.enums_src",
        "Py4GWCoreLib.py4gwcorelib_src",
        "Py4GWCoreLib.GlobalCache",
        "Py4GWCoreLib.HeroAI",
        "Py4GWCoreLib.HeroAI.hex_removal_src",
    ):
        _install_package(monkeypatch, package_name)

    class _Profession:
        _None = 0
        Warrior = 1
        Ranger = 2
        Monk = 3
        Necromancer = 4
        Mesmer = 5
        Elementalist = 6
        Assassin = 7
        Ritualist = 8
        Paragon = 9
        Dervish = 10

        def __iter__(self) -> Any:
            return iter(
                (
                    self._None,
                    self.Warrior,
                    self.Ranger,
                    self.Monk,
                    self.Necromancer,
                    self.Mesmer,
                    self.Elementalist,
                    self.Assassin,
                    self.Ritualist,
                    self.Paragon,
                    self.Dervish,
                )
            )

    profession = _Profession()
    profession_names = {
        profession._None: "None",
        profession.Warrior: "Warrior",
        profession.Ranger: "Ranger",
        profession.Monk: "Monk",
        profession.Necromancer: "Necromancer",
        profession.Mesmer: "Mesmer",
        profession.Elementalist: "Elementalist",
        profession.Assassin: "Assassin",
        profession.Ritualist: "Ritualist",
        profession.Paragon: "Paragon",
        profession.Dervish: "Dervish",
    }
    game_enums = _install_module(monkeypatch, "Py4GWCoreLib.enums_src.GameData_enums")
    game_enums.__dict__.update(Profession=profession, Profession_Names=profession_names)

    system_module = _install_module(monkeypatch, "PySystem")
    system_module.__dict__["Console"] = types.SimpleNamespace(
        MessageType=types.SimpleNamespace(Info=1, Warning=2, Error=3),
        Log=lambda *_args, **_kwargs: None,
    )
    callback_module = _install_module(monkeypatch, "PyCallback")
    callback_module.__dict__.update(
        Phase=types.SimpleNamespace(PreUpdate=1),
        PyCallback=types.SimpleNamespace(
            Register=lambda *_args, **_kwargs: None,
            RemoveByName=lambda *_args, **_kwargs: None,
        ),
    )

    json_factory = _install_module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.JsonFactory")
    json_factory.__dict__["JsonFactory"] = type("JsonFactory", (), {})
    frame_cache = _load_source(
        monkeypatch,
        "Py4GWCoreLib.py4gwcorelib_src.FrameCache",
        _REPO_ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "FrameCache.py",
    )

    skill_id_calls: list[str] = []
    hex_name_cell: list[str | None] = [None]
    skill = types.SimpleNamespace(
        GetID=lambda name: skill_id_calls.append(name) or (500 if name == hex_name_cell[0] else 0),
        Flags=types.SimpleNamespace(IsHex=lambda skill_id: skill_id == 500),
    )
    effects = types.SimpleNamespace(GetBuffs=lambda _agent_id: (), GetEffects=lambda _agent_id: ())
    corelib = sys.modules["Py4GWCoreLib"]
    corelib.__dict__["GLOBAL_CACHE"] = types.SimpleNamespace(Skill=skill, Effects=effects)
    global_cache_package = sys.modules["Py4GWCoreLib.GlobalCache"]

    priority = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.HexRemovalPriority",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "HexRemovalPriority.py",
    )
    global_cache_package.__dict__["HexRemovalPriority"] = priority
    hex_name = next(iter(priority._HEX_DEFAULTS))
    hex_name_cell[0] = hex_name

    active_identity = ["account-a@example.test", "Character A"]
    player = types.SimpleNamespace(
        GetAccountEmail=lambda: active_identity[0],
        GetName=lambda: active_identity[1],
        GetXY=lambda: (0.0, 0.0),
    )
    player_module = _install_module(monkeypatch, "Py4GWCoreLib.Player")
    player_module.__dict__["Player"] = player

    professions = {42: profession.Monk}
    agent = types.SimpleNamespace(
        IsAlive=lambda _agent_id: True,
        GetProfessions=lambda agent_id: (professions.get(agent_id, profession.Monk), 0),
        GetXY=lambda _agent_id: (10.0, 0.0),
    )
    agent_module = _install_module(monkeypatch, "Py4GWCoreLib.Agent")
    agent_module.__dict__["Agent"] = agent
    filters = types.SimpleNamespace(
        ByDistance=lambda agents, *_args: list(agents),
        ByCondition=lambda agents, condition: [agent_id for agent_id in agents if condition(agent_id)],
    )
    agent_array_module = _install_module(monkeypatch, "Py4GWCoreLib.AgentArray")
    agent_array_module.__dict__["AgentArray"] = types.SimpleNamespace(
        GetAllyArray=lambda: [42],
        Filter=filters,
    )
    map_module = _install_module(monkeypatch, "Py4GWCoreLib.Map")
    map_module.__dict__["Map"] = types.SimpleNamespace(GetMapID=lambda: 99)

    effect_scan_calls: list[int] = []
    routines = types.SimpleNamespace(
        Checks=types.SimpleNamespace(
            Agents=types.SimpleNamespace(
                GetBuffs=lambda agent_id: effect_scan_calls.append(agent_id)
                or [types.SimpleNamespace(SkillId=500, Type=2, Remaining=5000)]
            )
        ),
        Party=types.SimpleNamespace(IsPartyMember=lambda _agent_id: True),
    )
    corelib.__dict__["Routines"] = routines

    config = _load_source(
        monkeypatch,
        "Py4GWCoreLib.HeroAI.hex_removal_src.hex_removal_config",
        _REPO_ROOT / "Py4GWCoreLib" / "HeroAI" / "hex_removal_src" / "hex_removal_config.py",
    )
    config.__dict__.update(
        _apply_debug_flags_to_runtime=lambda _state: None,
        _cache_key=("", ""),
        _cache_state=None,
    )
    profile_loads: list[tuple[str, str]] = []
    profile_states: dict[tuple[str, str], Any] = {}

    def load_profile(email: str, character_name: str) -> Any:
        profile_loads.append((email, character_name))
        return profile_states.get((email, character_name), config.ConfigState())

    config.__dict__["_load_from_store"] = load_profile

    return _HexRuntime(
        priority=priority,
        config=config,
        active_identity=active_identity,
        profile_loads=profile_loads,
        profile_states=profile_states,
        skill_id_calls=skill_id_calls,
        hex_name=hex_name,
        professions=professions,
        effect_scan_calls=effect_scan_calls,
    )


def _entry(
    priority: Any,
    *,
    caster: Any,
    melee: Any | None = None,
    by_profession: dict[int, Any] | None = None,
) -> Any:
    return priority.HexRemovalEntry(
        caster=caster,
        ranged_martial=caster,
        melee=caster if melee is None else melee,
        by_profession={} if by_profession is None else by_profession,
    )


def _set_profile(hex_runtime: _HexRuntime, identity: tuple[str, str], entry: Any) -> None:
    config = hex_runtime.config
    state = config.ConfigState(hexes={hex_runtime.hex_name: config.HexEntryState(entry=entry)})
    hex_runtime.profile_states[identity] = state


def test_public_classification_tracks_character_switches_without_manual_invalidation(
    hex_runtime: _HexRuntime,
) -> None:
    priority = hex_runtime.priority
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character A"),
        _entry(priority, caster=priority.HexRemovalPriority.HIGH),
    )
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character B"),
        _entry(priority, caster=priority.HexRemovalPriority.NONE),
    )

    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.HIGH

    hex_runtime.active_identity[:] = ["account-a@example.test", "Character B"]
    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.NONE

    hex_runtime.active_identity[:] = ["account-a@example.test", "Character A"]
    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.HIGH
    assert hex_runtime.profile_loads == [
        ("account-a@example.test", "Character A"),
        ("account-a@example.test", "Character B"),
        ("account-a@example.test", "Character A"),
    ]


def test_unchanged_identity_reuses_resolved_catalogue(hex_runtime: _HexRuntime) -> None:
    priority = hex_runtime.priority
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character A"),
        _entry(priority, caster=priority.HexRemovalPriority.HIGH),
    )

    expected = priority.classify_hex_for_removal(500, 42)
    calls_after_build = len(hex_runtime.skill_id_calls)
    loaded_after_build = list(hex_runtime.profile_loads)
    assert priority.classify_hex_for_removal(500, 42) == expected
    assert priority.classify_hex_for_removal(500, 42) == expected

    assert len(hex_runtime.skill_id_calls) == calls_after_build
    assert hex_runtime.profile_loads == loaded_after_build


def test_profession_override_refreshes_after_same_map_character_switch(hex_runtime: _HexRuntime) -> None:
    priority = hex_runtime.priority
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character A"),
        _entry(
            priority,
            caster=priority.HexRemovalPriority.LOW,
            melee=priority.HexRemovalPriority.MEDIUM,
        ),
    )
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character B"),
        _entry(
            priority,
            caster=priority.HexRemovalPriority.HIGH,
            melee=priority.HexRemovalPriority.HIGH,
            by_profession={3: priority.HexRemovalPriority.NONE},
        ),
    )
    hex_runtime.professions[42] = 1
    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.MEDIUM

    hex_runtime.active_identity[:] = ["account-a@example.test", "Character B"]
    hex_runtime.professions[42] = 3
    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.NONE
    assert priority.classify_hex_with_role(500, priority.TargetRole.CASTER, 5) == priority.HexRemovalPriority.HIGH


def test_shared_selector_frame_cache_is_scoped_to_profile_generation(hex_runtime: _HexRuntime) -> None:
    priority = hex_runtime.priority
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character A"),
        _entry(priority, caster=priority.HexRemovalPriority.HIGH),
    )
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Character B"),
        _entry(priority, caster=priority.HexRemovalPriority.NONE),
    )

    assert priority.get_hexed_ally_array() == [42]
    assert priority.get_hexed_ally_array() == [42]
    assert len(hex_runtime.effect_scan_calls) == 1

    hex_runtime.active_identity[:] = ["account-a@example.test", "Character B"]
    assert priority.get_hexed_ally_array() == []
    assert len(hex_runtime.effect_scan_calls) == 2

    hex_runtime.active_identity[:] = ["account-a@example.test", "Character A"]
    assert priority.get_hexed_ally_array() == [42]
    assert len(hex_runtime.effect_scan_calls) == 3


def test_account_change_and_unresolved_startup_identity_do_not_reuse_old_profile(
    hex_runtime: _HexRuntime,
) -> None:
    priority = hex_runtime.priority
    default_entry = priority._HEX_DEFAULTS[hex_runtime.hex_name]
    default_priority = default_entry.for_target(priority.TargetRole.CASTER, 3)
    alternate_priority = next(value for value in priority.HexRemovalPriority if value != default_priority)
    _set_profile(
        hex_runtime,
        ("account-a@example.test", "Same Character"),
        _entry(priority, caster=alternate_priority),
    )
    _set_profile(
        hex_runtime,
        ("account-b@example.test", "Same Character"),
        _entry(priority, caster=priority.HexRemovalPriority.NONE),
    )

    hex_runtime.active_identity[:] = ["", ""]
    assert priority.classify_hex_for_removal(500, 42) == default_priority

    hex_runtime.active_identity[:] = ["account-a@example.test", "Same Character"]
    assert priority.classify_hex_for_removal(500, 42) == alternate_priority

    hex_runtime.active_identity[:] = ["account-b@example.test", "Same Character"]
    assert priority.classify_hex_for_removal(500, 42) == priority.HexRemovalPriority.NONE
