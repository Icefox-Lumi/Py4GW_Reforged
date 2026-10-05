from __future__ import annotations

import importlib.util
import random
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_NAMES = (
    "Energy Surge",
    "Panic",
    "Ineptitude",
    "Heroic Refrain",
    "Blood is Power",
    "Soul Twisting",
    "Shelter",
    "Union",
    "Healing Burst",
    "Together as One",
)
_SUPPORTED_ROLES = (
    "ENERGY_SURGE",
    "PANIC",
    "INEPTITUDE",
    "HEROIC_REFRAIN",
    "BIP",
    "SOUL_TWISTING",
    "HEALING_BURST",
    "TAO",
)


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


def _load_global_cache_owner(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    corelib = sys.modules["Py4GWCoreLib"]
    corelib.__dict__["ThrottledTimer"] = type("ThrottledTimer", (), {})
    action_queue_module = _install_module(monkeypatch, "Py4GWCoreLib.Py4GWcorelib")
    action_queue_module.__dict__["ActionQueueManager"] = type("ActionQueueManager", (), {})

    dependencies = {
        "CameraCache": ("CameraCache",),
        "EffectCache": ("EffectsCache",),
        "InventoryCache": ("InventoryCache",),
        "ItemCache": ("ItemArray", "ItemCache", "RawItemCache"),
        "MerchantCache": ("TradingCache",),
        "PartyCache": ("PartyCache",),
        "QuestCache": ("QuestCache",),
        "SharedMemory": ("Py4GWSharedMemoryManager",),
        "SkillbarCache": ("SkillbarCache",),
        "SkillCache": ("SkillCache",),
    }
    for module_name, class_names in dependencies.items():
        dependency_module = _install_module(monkeypatch, f"Py4GWCoreLib.GlobalCache.{module_name}")
        for class_name in class_names:
            dependency_module.__dict__[class_name] = type(class_name, (), {})

    module = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.GlobalCache",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "GlobalCache.py",
    )
    return module.GlobalCache


def _load_environment_upkeeper(
    monkeypatch: pytest.MonkeyPatch, runtime: _Runtime, global_cache: Any
) -> tuple[types.ModuleType, type[Any]]:
    corelib = sys.modules["Py4GWCoreLib"]

    class _ActionQueueManager:
        def ResetAllQueues(self) -> None:
            pass

        def ResetNonTransitionQueues(self) -> None:
            pass

        def ProcessQueue(self, _queue_name: str) -> None:
            pass

    class _Overlay:
        def __init__(self) -> None:
            pass

        def UpkeepTextures(self) -> None:
            pass

    class _ThrottledTimer:
        def __init__(self, _interval_ms: int) -> None:
            pass

        def IsExpired(self) -> bool:
            return False

        def Reset(self) -> None:
            pass

    class _LootFilters:
        map_change_calls = 0

        def __init__(self) -> None:
            pass

        def on_map_change(self) -> None:
            type(self).map_change_calls += 1

    corelib.__dict__.update(
        GLOBAL_CACHE=global_cache,
        ActionQueueManager=_ActionQueueManager,
        Overlay=_Overlay,
        ThrottledTimer=_ThrottledTimer,
        Routines=types.SimpleNamespace(
            Checks=types.SimpleNamespace(
                Map=types.SimpleNamespace(
                    MapValid=lambda: runtime.ready and not runtime.cinematic and runtime.party_loaded,
                )
            )
        ),
    )

    _install_module(monkeypatch, "PyImGui")
    hotkey_module = _install_module(monkeypatch, "Py4GWCoreLib.HotkeyManager")
    hotkey_module.__dict__["HOTKEY_MANAGER"] = types.SimpleNamespace(update=lambda: None)
    _install_package(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src")
    _install_package(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings")
    loot_module = _install_module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters")
    loot_module.__dict__["LootFilters"] = _LootFilters

    module = _load_source(
        monkeypatch,
        "test_environment_upkeeper",
        _REPO_ROOT / "Widgets" / "System" / "Environment Upkeeper.py",
    )
    return module, _LootFilters


class _Runtime:
    def __init__(self) -> None:
        self.ready = True
        self.loading = False
        self.cinematic = False
        self.pvp = False
        self.outpost = True
        self.explorable = False
        self.map_id = 1
        self.party_loaded = True
        self.party_size_override: int | None = None
        self.login_number = 11
        self.agent_id = 1001
        self.account_email = "mesmer@example.test"
        self.character_name = "Mesmer A"
        self.players: list[Any] = []
        self.heroes: list[Any] = []
        self.henchmen: list[Any] = []
        self.professions: dict[int, int] = {}
        self.bars: dict[int, tuple[int, ...]] = {}
        self.skill_types: dict[int, int] = {}
        self.skill_ids = {name: 100 + index for index, name in enumerate(_SKILL_NAMES)}
        self.attack_skill_id = 999
        self.local_agent_by_login = {self.login_number: self.agent_id}
        self.hero_agent_by_position_override: dict[int, int] = {}
        self.hero_agent_positions: list[int] = []
        self.hero_skillbar_positions: list[int] = []
        self.skillbar_agent_id: int | None = None
        self.profession: Any = None
        self.skill_type: Any = None
        self.players = [types.SimpleNamespace(login_number=self.login_number)]
        self.professions[self.agent_id] = 0
        self.bars[self.agent_id] = tuple(900 + index for index in range(8))

    @property
    def party_size(self) -> int:
        if self.party_size_override is not None:
            return self.party_size_override
        return len(self.players) + len(self.heroes) + len(self.henchmen)

    def agent_id_at_party_position(self, party_position: int) -> int:
        if party_position == 0:
            return self.agent_id
        hero_roster_index = party_position - 1
        if 0 <= hero_roster_index < len(self.heroes):
            return int(self.heroes[hero_roster_index].agent_id)
        return 0

    def skill_ids_at_party_position(self, party_position: int) -> tuple[int, ...]:
        agent_id = self.agent_id_at_party_position(party_position)
        return self.bars.get(agent_id, ())

    def set_identity(self, login_number: int, account_email: str, character_name: str) -> None:
        old_login = self.login_number
        self.login_number = login_number
        self.account_email = account_email
        self.character_name = character_name
        self.players = [
            types.SimpleNamespace(
                login_number=login_number if int(player.login_number) == old_login else int(player.login_number)
            )
            for player in self.players
        ]
        self.local_agent_by_login.pop(old_login, None)
        self.local_agent_by_login[login_number] = self.agent_id


@pytest.fixture
def cleansing_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[_Runtime, types.ModuleType]:
    runtime = _Runtime()
    corelib = _install_package(monkeypatch, "Py4GWCoreLib")
    _install_package(monkeypatch, "Py4GWCoreLib.enums_src")
    _load_source(
        monkeypatch,
        "Py4GWCoreLib.enums_src.GameData_enums",
        _REPO_ROOT / "Py4GWCoreLib" / "enums_src" / "GameData_enums.py",
    )
    _install_package(monkeypatch, "Py4GWCoreLib.GlobalCache")

    map_api = types.SimpleNamespace(
        IsMapReady=lambda: runtime.ready,
        IsMapLoading=lambda: runtime.loading,
        IsInCinematic=lambda: runtime.cinematic,
        IsPVP=lambda: runtime.pvp,
        IsOutpost=lambda: runtime.outpost,
        IsExplorable=lambda: runtime.explorable,
        GetMapID=lambda: runtime.map_id,
    )
    player_api = types.SimpleNamespace(
        IsPlayerLoaded=lambda: runtime.ready,
        GetAgentID=lambda: runtime.agent_id,
        GetLoginNumber=lambda: runtime.login_number,
        GetAccountEmail=lambda: runtime.account_email,
        GetName=lambda: runtime.character_name,
    )
    agent_api = types.SimpleNamespace(
        GetProfessions=lambda agent_id: (runtime.professions.get(agent_id, 0), 0),
    )

    def get_hero_agent_id_by_party_position(party_position: int) -> int:
        runtime.hero_agent_positions.append(party_position)
        if party_position in runtime.hero_agent_by_position_override:
            return runtime.hero_agent_by_position_override[party_position]
        return runtime.agent_id_at_party_position(party_position)

    party_api = types.SimpleNamespace(
        IsPartyLoaded=lambda: runtime.party_loaded,
        GetPlayers=lambda: tuple(runtime.players),
        GetHeroes=lambda: tuple(runtime.heroes),
        GetHenchmen=lambda: tuple(runtime.henchmen),
        GetPartySize=lambda: runtime.party_size,
        Players=types.SimpleNamespace(
            GetAgentIDByLoginNumber=lambda login: runtime.local_agent_by_login.get(login, 0),
        ),
        Heroes=types.SimpleNamespace(
            GetHeroAgentIDByPartyPosition=get_hero_agent_id_by_party_position,
        ),
    )
    skill_api = types.SimpleNamespace(
        GetID=lambda name: runtime.skill_ids.get(name, 0),
        GetType=lambda skill_id: (runtime.skill_types.get(skill_id, 0), ""),
    )
    corelib.__dict__.update(
        Agent=agent_api,
        GLOBAL_CACHE=types.SimpleNamespace(Party=party_api, Skill=skill_api),
        Map=map_api,
        Player=player_api,
    )

    class _FakeSkillbar:
        def __init__(self) -> None:
            self.agent_id = 0
            self.skills: list[Any] = []

        @staticmethod
        def _slots(skill_ids: tuple[int, ...]) -> list[Any]:
            return [types.SimpleNamespace(id=types.SimpleNamespace(id=skill_id)) for skill_id in skill_ids]

        def GetContext(self) -> None:
            self.agent_id = runtime.agent_id if runtime.skillbar_agent_id is None else runtime.skillbar_agent_id
            self.skills = self._slots(runtime.bars.get(runtime.agent_id, ()))

        def GetHeroSkillbar(self, hero_position: int) -> list[Any]:
            runtime.hero_skillbar_positions.append(hero_position)
            return self._slots(runtime.skill_ids_at_party_position(hero_position))

    skillbar_module = _install_module(monkeypatch, "PySkillbar")
    skillbar_module.__dict__["Skillbar"] = _FakeSkillbar

    module = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.CleansingContext",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "CleansingContext.py",
    )
    runtime.profession = module.Profession
    runtime.skill_type = sys.modules["Py4GWCoreLib.enums_src.GameData_enums"].SkillType
    runtime.professions[runtime.agent_id] = int(module.Profession.Mesmer)
    return runtime, module


def _skill_ids(runtime: _Runtime, module: types.ModuleType) -> Any:
    return module.resolve_supported_skill_ids(lambda name: runtime.skill_ids[name])


def _profession_for(module: types.ModuleType, role: Any) -> int:
    profession_by_role = {
        module.CleansingRole.ENERGY_SURGE: module.Profession.Mesmer,
        module.CleansingRole.PANIC: module.Profession.Mesmer,
        module.CleansingRole.INEPTITUDE: module.Profession.Mesmer,
        module.CleansingRole.HEROIC_REFRAIN: module.Profession.Paragon,
        module.CleansingRole.BIP: module.Profession.Necromancer,
        module.CleansingRole.SOUL_TWISTING: module.Profession.Ritualist,
        module.CleansingRole.HEALING_BURST: module.Profession.Monk,
        module.CleansingRole.TAO: module.Profession.Ranger,
    }
    return int(profession_by_role[role])


def _role_bar(runtime: _Runtime, module: types.ModuleType, role: Any, utility_seed: int = 2000) -> tuple[int, ...]:
    skill_ids = _skill_ids(runtime, module)
    anchor_by_role = {
        module.CleansingRole.ENERGY_SURGE: (skill_ids.energy_surge,),
        module.CleansingRole.PANIC: (skill_ids.panic,),
        module.CleansingRole.INEPTITUDE: (skill_ids.ineptitude,),
        module.CleansingRole.HEROIC_REFRAIN: (skill_ids.heroic_refrain,),
        module.CleansingRole.BIP: (skill_ids.blood_is_power,),
        module.CleansingRole.SOUL_TWISTING: (skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union),
        module.CleansingRole.HEALING_BURST: (skill_ids.healing_burst,),
        module.CleansingRole.TAO: (skill_ids.together_as_one, runtime.attack_skill_id),
    }
    bar = list(anchor_by_role[role])
    while len(bar) < 8:
        bar.append(utility_seed + len(bar))
    return tuple(bar)


def _set_player_role(runtime: _Runtime, module: types.ModuleType, role: Any) -> None:
    runtime.professions[runtime.agent_id] = _profession_for(module, role)
    runtime.bars[runtime.agent_id] = _role_bar(runtime, module, role)
    if role is module.CleansingRole.TAO:
        runtime.skill_types[runtime.attack_skill_id] = int(runtime.skill_type.Attack)


def _add_hero(
    runtime: _Runtime,
    module: types.ModuleType,
    role: Any,
    *,
    hero_id: int,
    agent_id: int,
    owner_id: int | None = None,
) -> Any:
    hero = types.SimpleNamespace(
        agent_id=agent_id,
        owner_player_id=runtime.login_number if owner_id is None else owner_id,
        hero_id=hero_id,
    )
    runtime.heroes.append(hero)
    runtime.professions[agent_id] = _profession_for(module, role)
    runtime.bars[agent_id] = _role_bar(runtime, module, role, utility_seed=3000 + hero_id * 10)
    if role is module.CleansingRole.TAO:
        runtime.skill_types[runtime.attack_skill_id] = int(runtime.skill_type.Attack)
    return hero


def _configure_team(runtime: _Runtime, module: types.ModuleType, roles: list[Any]) -> None:
    runtime.heroes.clear()
    runtime.players = [types.SimpleNamespace(login_number=runtime.login_number)]
    _set_player_role(runtime, module, roles[0])
    for index, role in enumerate(roles[1:], start=1):
        _add_hero(runtime, module, role, hero_id=100 + index, agent_id=2000 + index)
    runtime.party_size_override = None


def _member_records(module: types.ModuleType, roles: list[Any]) -> tuple[Any, ...]:
    records = []
    for index, role in enumerate(roles):
        identity = module.MemberIdentity(module.MemberKind.PLAYER, index + 1, index + 1, index + 100)
        records.append(
            module.MemberRecord(
                identity=identity,
                role=role,
                candidate_role=role,
                evidence_source=module.EvidenceSource.LOCAL_PLAYER,
                reason="test evidence",
            )
        )
    return tuple(records)


def _supported_role(module: types.ModuleType, name: str) -> Any:
    return getattr(module.CleansingRole, name)


@pytest.mark.parametrize("role_name", _SUPPORTED_ROLES)
def test_role_recognition_accepts_each_supported_family(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], role_name: str
) -> None:
    runtime, module = cleansing_runtime
    role = _supported_role(module, role_name)
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.PLAYER, 1, 1, 1001),
        source=module.EvidenceSource.LOCAL_PLAYER,
        primary_profession=_profession_for(module, role),
        skill_ids=_role_bar(runtime, module, role),
        ownership_proven=True,
        weapon_attack_equipped=True if role is module.CleansingRole.TAO else None,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is role
    ), f"role={role_name}; expected={role}; observed={result}; reason={result.reason}"


@pytest.mark.parametrize(
    ("missing_anchor", "expected_name"),
    (("Shelter", "Shelter"), ("Union", "Union")),
)
def test_soul_twisting_requires_both_protection_anchors(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], missing_anchor: str, expected_name: str
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    anchors = [skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union]
    anchors.remove(getattr(skill_ids, missing_anchor.casefold()))
    bar = tuple(anchors + [2200 + index for index in range(8 - len(anchors))])
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Ritualist),
        skill_ids=bar,
        ownership_proven=True,
    )

    result = module.recognize_role(evidence, skill_ids)

    assert result.candidate_role is module.CleansingRole.UNKNOWN, f"missing={expected_name}; observed={result}"
    assert expected_name in result.reason, f"missing={expected_name}; reason={result.reason}"


@pytest.mark.parametrize("attack_evidence", (False, None))
def test_tao_requires_positive_weapon_attack_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], attack_evidence: bool | None
) -> None:
    runtime, module = cleansing_runtime
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Ranger),
        skill_ids=_role_bar(runtime, module, module.CleansingRole.TAO),
        ownership_proven=True,
        weapon_attack_equipped=attack_evidence,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"attack_evidence={attack_evidence}; expected UNKNOWN; observed={result}"


def test_role_recognition_rejects_wrong_profession_unsupported_anchor_and_incomplete_bar(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    identity = module.MemberIdentity(module.MemberKind.PLAYER, 11, 11, 1001)

    wrong_profession = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Ranger),
        (skill_ids.energy_surge, *range(3000, 3007)),
        True,
        True,
    )
    unsupported_elite = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Mesmer),
        tuple(range(4000, 4008)),
        True,
    )
    incomplete = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Mesmer),
        (skill_ids.energy_surge, *range(5000, 5006)),
        True,
    )

    results = tuple(
        module.recognize_role(evidence, skill_ids) for evidence in (wrong_profession, unsupported_elite, incomplete)
    )

    assert all(
        result.candidate_role is module.CleansingRole.UNKNOWN for result in results
    ), f"expected wrong profession, unsupported anchor, and incomplete bar to be UNKNOWN; observed={results}"
    assert "profession" in results[0].reason
    assert "anchor" in results[1].reason
    assert "incomplete" in results[2].reason


@pytest.mark.parametrize("profession_name", ("Warrior", "Elementalist"))
def test_unrelated_primary_professions_do_not_match_supported_roles(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], profession_name: str
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(getattr(module.Profession, profession_name)),
        skill_ids=(skill_ids.energy_surge, *range(6000, 6007)),
        ownership_proven=True,
    )

    result = module.recognize_role(evidence, skill_ids)

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"profession={profession_name}; supported elite must not identify this role; observed={result}"


def test_role_recognition_rejects_ambiguous_ownership(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 99, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Mesmer),
        skill_ids=_role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE),
        ownership_proven=False,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"ambiguous ownership must fail closed; observed={result}"
    assert "ownership" in result.reason


def test_skill_names_resolve_through_the_existing_skill_cache_surface(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    result = module.resolve_supported_skill_ids(lambda name: runtime.skill_ids[name])

    assert tuple(getattr(result, field) for field, _ in module.SUPPORTED_SKILL_NAMES) == tuple(
        runtime.skill_ids[name] for name in _SKILL_NAMES
    ), f"resolved={result.all_anchor_ids}; expected names={_SKILL_NAMES}"


@pytest.mark.parametrize(
    "roles",
    (
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "PANIC",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "HEALING_BURST",
        ),
        ("HEROIC_REFRAIN", "BIP", "SOUL_TWISTING", "INEPTITUDE", "ENERGY_SURGE", "ENERGY_SURGE", "ENERGY_SURGE", "TAO"),
    ),
)
def test_composition_matcher_accepts_only_the_four_supported_histograms_in_any_order(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], roles: tuple[str, ...]
) -> None:
    _, module = cleansing_runtime
    role_list = [_supported_role(module, role) for role in roles]
    random.Random(41).shuffle(role_list)

    result = module.match_supported_composition(_member_records(module, role_list), declared_party_size=8)

    assert (
        result.status is module.CompositionStatus.ACTIVE
    ), f"roles={roles}; shuffled={role_list}; counts={result.role_counts}; reason={result.reason}"
    assert result.is_proven
    assert result.member_count == 8


@pytest.mark.parametrize(
    "roles",
    (
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "PANIC",
            "HEALING_BURST",
        ),
        ("HEROIC_REFRAIN", "BIP", "SOUL_TWISTING", "INEPTITUDE", "ENERGY_SURGE", "ENERGY_SURGE", "PANIC", "TAO"),
    ),
)
def test_composition_matcher_rejects_missing_core_and_duplicate_or_multiple_substitutions(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], roles: tuple[str, ...]
) -> None:
    _, module = cleansing_runtime
    members = _member_records(module, [_supported_role(module, role) for role in roles])

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"unsupported roles={roles}; observed={result}"
    assert not result.is_proven


def test_composition_matcher_rejects_unknown_candidate_even_when_candidate_is_energy_surge(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    members = list(_member_records(module, roles))
    member = members[-1]
    members[-1] = module.MemberRecord(
        identity=member.identity,
        role=module.CleansingRole.UNKNOWN,
        candidate_role=module.CleansingRole.ENERGY_SURGE,
        evidence_source=member.evidence_source,
        reason="candidate anchor lacks original-bar provenance",
    )

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"candidate role is not proven; observed={result}"
    assert "UNKNOWN" in result.reason


@pytest.mark.parametrize("member_count", (7, 9))
def test_composition_matcher_rejects_wrong_party_size(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], member_count: int
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.ENERGY_SURGE] * member_count
    members = _member_records(module, roles)

    result = module.match_supported_composition(members, declared_party_size=member_count)

    assert result.status is module.CompositionStatus.FALLBACK, f"party_size={member_count}; observed={result}"
    assert "exactly 8" in result.reason


def test_composition_matcher_rejects_declared_party_size_mismatch_and_duplicate_identity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.ENERGY_SURGE] * 8
    members = list(_member_records(module, roles))
    mismatch = module.match_supported_composition(members, declared_party_size=9)
    members[-1] = module.MemberRecord(
        identity=members[0].identity,
        role=members[-1].role,
        candidate_role=members[-1].candidate_role,
        evidence_source=members[-1].evidence_source,
        reason=members[-1].reason,
    )
    duplicate = module.match_supported_composition(members)

    assert (
        mismatch.status is module.CompositionStatus.FALLBACK and "incomplete" in mismatch.reason
    ), f"declared size mismatch should fail; observed={mismatch}"
    assert (
        duplicate.status is module.CompositionStatus.FALLBACK and "duplicate" in duplicate.reason
    ), f"duplicate identity should fail; observed={duplicate}"


def test_random_team_with_one_valid_es_candidate_does_not_prove_mesmerway(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.UNKNOWN] * 8
    roles[3] = module.CleansingRole.ENERGY_SURGE
    members = list(_member_records(module, roles))
    candidate = members[3]
    members[3] = module.MemberRecord(
        identity=candidate.identity,
        role=candidate.role,
        candidate_role=candidate.role,
        evidence_source=candidate.evidence_source,
        reason="equipped E-Surge candidate",
    )

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"one E-Surge is not a supported team; observed={result}"
    assert dict(result.role_counts)[module.CleansingRole.ENERGY_SURGE] == 1


def test_context_proves_a_supported_outpost_team_and_revalidates_it_in_explorable(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()

    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    explorable = context.Refresh()

    assert outpost.supported_composition_proven, f"outpost roles should be proven; observed={outpost.composition}"
    assert (
        explorable.supported_composition_proven
    ), f"fresh explorable bars matching the ready-outpost baseline should prove roles; observed={explorable.composition}"
    assert explorable.revision > outpost.revision
    assert explorable.lifecycle_epoch > outpost.lifecycle_epoch


@pytest.mark.parametrize("attack_equipped", (True, False))
def test_context_uses_skill_type_attack_for_tao_guard(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], attack_equipped: bool
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.TAO,
    ]
    _configure_team(runtime, module, roles)
    tao_hero = runtime.heroes[-1]
    if not attack_equipped:
        bar = runtime.bars[tao_hero.agent_id]
        runtime.bars[tao_hero.agent_id] = (bar[0], *bar[2:], 9900)
    snapshot = module.CleansingContext().Refresh()
    tao_member = next(member for member in snapshot.members if member.identity.agent_id == tao_hero.agent_id)

    if attack_equipped:
        assert tao_member.role is module.CleansingRole.TAO, f"Attack skill type should prove TaO; observed={tao_member}"
        assert snapshot.supported_composition_proven, f"TaO substitution should match; observed={snapshot.composition}"
    else:
        assert (
            tao_member.role is module.CleansingRole.UNKNOWN
        ), f"TaO without Attack must be UNKNOWN; observed={tao_member}"
        assert not snapshot.supported_composition_proven


def test_local_skillbar_agent_mismatch_is_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.skillbar_agent_id = runtime.agent_id + 1

    snapshot = module.CleansingContext().Refresh()

    assert (
        snapshot.members[0].role is module.CleansingRole.UNKNOWN
    ), f"local bar owner mismatch must not classify the player's role; observed={snapshot.members[0]}"
    assert "ownership" in snapshot.members[0].reason


def test_copied_supported_elite_without_matching_outpost_baseline_remains_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    _set_player_role(runtime, module, module.CleansingRole.PANIC)

    explorable = context.Refresh()
    member = explorable.members[0]

    assert outpost.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert (
        member.role is module.CleansingRole.UNKNOWN
    ), f"copied Panic must not replace baseline E-Surge; observed={member}"
    assert member.candidate_role is module.CleansingRole.PANIC
    assert not explorable.supported_composition_proven


def test_utility_skill_changes_preserve_a_proven_core_role(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    context.Refresh()
    for agent_id, bar in tuple(runtime.bars.items()):
        runtime.bars[agent_id] = (*bar[:3], 8000 + agent_id, *bar[4:])
    outpost = context.Refresh()

    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    for agent_id, bar in tuple(runtime.bars.items()):
        runtime.bars[agent_id] = (*bar[:4], 9000 + agent_id, *bar[5:])
    explorable = context.Refresh()

    assert (
        outpost.supported_composition_proven
    ), f"utility changes in outpost preserve roles; observed={outpost.composition}"
    assert (
        explorable.supported_composition_proven
    ), f"unrelated utility changes in explorable preserve baseline anchors; observed={explorable.composition}"


def test_supported_to_unsupported_bar_clears_the_outpost_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    context = module.CleansingContext()
    context.Refresh()
    original_bar = runtime.bars[runtime.agent_id]
    runtime.bars[runtime.agent_id] = tuple(7000 + index for index in range(8))
    unsupported = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.bars[runtime.agent_id] = original_bar
    returned = context.Refresh()

    assert unsupported.members[0].role is module.CleansingRole.UNKNOWN
    assert (
        returned.members[0].role is module.CleansingRole.UNKNOWN
    ), f"restored anchor cannot reuse a baseline invalidated by an unsupported bar; observed={returned.members[0]}"


def test_unsupported_to_supported_bar_establishes_a_new_outpost_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    runtime.bars[runtime.agent_id] = tuple(7000 + index for index in range(8))
    context = module.CleansingContext()
    unsupported = context.Refresh()
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    supported = context.Refresh()

    assert not unsupported.supported_composition_proven
    assert (
        supported.supported_composition_proven
    ), f"new valid outpost baseline should be proven; observed={supported.composition}"


def test_nonlocal_hero_and_hero_index_mismatch_are_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    _add_hero(
        runtime,
        module,
        module.CleansingRole.ENERGY_SURGE,
        hero_id=101,
        agent_id=2001,
        owner_id=99,
    )
    context = module.CleansingContext()
    nonlocal_snapshot = context.Refresh()
    local_hero = runtime.heroes[0]
    local_hero.owner_player_id = runtime.login_number
    local_hero.agent_id = 2002
    runtime.professions[2002] = int(module.Profession.Mesmer)
    runtime.bars[2002] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.hero_agent_by_position_override[1] = 2001
    mismatch = context.Refresh()

    assert nonlocal_snapshot.members[1].role is module.CleansingRole.UNKNOWN
    assert "not owned" in nonlocal_snapshot.members[1].reason
    assert mismatch.members[1].role is module.CleansingRole.UNKNOWN
    assert "index" in mismatch.members[1].reason


def test_live_party_positions_keep_zero_on_player_and_align_owned_hero_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.TAO,
    ]
    _configure_team(runtime, module, roles)
    first_hero, second_hero = runtime.heroes[:2]

    party = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.Party
    assert party.Heroes.GetHeroAgentIDByPartyPosition(0) == runtime.agent_id
    assert party.Heroes.GetHeroAgentIDByPartyPosition(1) == first_hero.agent_id
    assert party.Heroes.GetHeroAgentIDByPartyPosition(2) == second_hero.agent_id
    assert runtime.hero_agent_positions == [0, 1, 2]

    native_skillbar = sys.modules["PySkillbar"].Skillbar()
    native_skillbar.GetContext()
    bars_by_position = tuple(
        tuple(slot.id.id for slot in native_skillbar.GetHeroSkillbar(position)) for position in (0, 1, 2)
    )
    assert bars_by_position == (
        runtime.bars[runtime.agent_id],
        runtime.bars[first_hero.agent_id],
        runtime.bars[second_hero.agent_id],
    )
    assert runtime.hero_skillbar_positions == [0, 1, 2]
    assert bars_by_position[0] != bars_by_position[1]
    assert bars_by_position[1] != bars_by_position[2]

    runtime.hero_agent_positions.clear()
    runtime.hero_skillbar_positions.clear()
    snapshot = module.CleansingContext().Refresh()
    queried_positions = list(range(1, len(runtime.heroes) + 1))

    assert runtime.hero_agent_positions == queried_positions
    assert runtime.hero_skillbar_positions == queried_positions
    player = next(member for member in snapshot.members if member.identity.kind is module.MemberKind.PLAYER)
    hero_records = {
        member.identity.agent_id: member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO
    }
    assert player.role is module.CleansingRole.HEROIC_REFRAIN
    assert hero_records[first_hero.agent_id].role is module.CleansingRole.BIP
    assert hero_records[second_hero.agent_id].role is module.CleansingRole.SOUL_TWISTING
    assert (
        snapshot.supported_composition_proven
    ), f"correctly positioned heroes should complete the supported team: {snapshot.composition}"


@pytest.mark.parametrize("reuse_agent_id", (False, True))
def test_hero_replacement_or_agent_identity_reuse_does_not_reuse_old_role(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], reuse_agent_id: bool
) -> None:
    runtime, module = cleansing_runtime
    team = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, team)
    context = module.CleansingContext()
    context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    context.Refresh()

    old_hero = runtime.heroes[0]
    replacement_agent_id = old_hero.agent_id if reuse_agent_id else old_hero.agent_id + 500
    replacement_hero = types.SimpleNamespace(
        agent_id=replacement_agent_id,
        owner_player_id=runtime.login_number,
        hero_id=old_hero.hero_id + 500,
    )
    runtime.heroes[0] = replacement_hero
    runtime.professions[replacement_agent_id] = int(module.Profession.Mesmer)
    runtime.bars[replacement_agent_id] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    replaced = context.Refresh()

    record = next(member for member in replaced.members if member.identity.kind is module.MemberKind.HERO)
    assert (
        record.role is module.CleansingRole.UNKNOWN
    ), f"replacement identity must not inherit an old role; reuse_agent_id={reuse_agent_id}; observed={record}"
    assert record.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert not replaced.supported_composition_proven


def test_map_loading_clears_published_roles_and_same_map_reset_drops_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    active = context.Refresh()
    runtime.ready = False
    runtime.loading = True
    loading = context.Refresh()
    runtime.ready = True
    runtime.loading = False
    reset = context.Refresh()

    assert outpost.supported_composition_proven and active.supported_composition_proven
    assert not loading.ready and loading.members == (), f"loading must publish no previous roles; observed={loading}"
    assert loading.lifecycle_epoch > active.lifecycle_epoch
    assert not reset.supported_composition_proven
    assert all(
        member.role is module.CleansingRole.UNKNOWN for member in reset.members
    ), f"same-map lifecycle reset must discard prior baseline roles; observed={reset.members}"


@pytest.mark.parametrize("unsafe_state", ("loading", "party_unavailable", "cinematic"))
@pytest.mark.parametrize("supported_recovery", (True, False))
def test_environment_upkeeper_gate_invalidates_snapshot_without_running_normal_cache_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    unsafe_state: str,
    supported_recovery: bool,
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    runtime_cache = corelib.GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.Coroutines = []

    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    active = context.GetSnapshot()
    assert active.supported_composition_proven, f"precondition requires ACTIVE composition; observed={active}"
    assert refresh_calls == 1

    if unsafe_state == "loading":
        runtime.ready = False
        runtime.loading = True
    elif unsafe_state == "party_unavailable":
        runtime.party_loaded = False
    else:
        runtime.cinematic = True

    upkeeper.main()
    invalid = context.GetSnapshot()
    assert not invalid.ready and invalid.members == (), f"unsafe state must hide prior members; observed={invalid}"
    assert invalid.composition.status is module.CompositionStatus.FALLBACK
    assert invalid.revision > active.revision
    assert invalid.lifecycle_epoch == active.lifecycle_epoch + 1
    assert refresh_calls == 1, "normal cache refresh must stay gated while MapValid is false"

    upkeeper.main()
    repeated_invalid = context.GetSnapshot()
    assert repeated_invalid.revision == invalid.revision, "repeated unsafe frames must not churn revisions"
    assert repeated_invalid.lifecycle_epoch == invalid.lifecycle_epoch, "one unsafe period advances one epoch"
    assert refresh_calls == 1

    changed_core_hero = runtime.heroes[0]
    if not supported_recovery:
        runtime.bars[changed_core_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)

    runtime.ready = True
    runtime.loading = False
    runtime.party_loaded = True
    runtime.cinematic = False
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    upkeeper.main()
    recovered = context.GetSnapshot()

    assert refresh_calls == 2, "normal cache refresh resumes only after MapValid becomes true"
    if supported_recovery:
        assert recovered.supported_composition_proven, f"fresh matching evidence should restore ACTIVE; {recovered}"
    else:
        assert not recovered.supported_composition_proven
        assert recovered.composition.status is module.CompositionStatus.FALLBACK
        changed_record = next(
            member for member in recovered.members if member.identity.agent_id == changed_core_hero.agent_id
        )
        assert changed_record.role is module.CleansingRole.UNKNOWN


@pytest.mark.parametrize("replacement", ("character", "hero_agent", "party_hero"))
def test_environment_upkeeper_rechecks_identity_after_suppressed_lifecycle_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    runtime_cache = corelib.GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.Coroutines = []

    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    assert context.GetSnapshot().supported_composition_proven
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    upkeeper.main()
    active = context.GetSnapshot()
    assert active.supported_composition_proven, f"precondition requires active explorable context; {active}"

    runtime.ready = False
    runtime.loading = True
    upkeeper.main()
    invalid = context.GetSnapshot()
    assert not invalid.ready and not invalid.supported_composition_proven
    assert refresh_calls == 2

    if replacement == "character":
        runtime.set_identity(12, "mesmer@example.test", "Mesmer B")
    elif replacement == "hero_agent":
        hero = runtime.heroes[0]
        hero.agent_id += 500
        runtime.professions[hero.agent_id] = int(module.Profession.Paragon)
        runtime.bars[hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    else:
        old_hero = runtime.heroes[0]
        replacement_agent_id = old_hero.agent_id + 500
        replacement_hero = types.SimpleNamespace(
            agent_id=replacement_agent_id,
            owner_player_id=runtime.login_number,
            hero_id=old_hero.hero_id + 500,
        )
        runtime.heroes[0] = replacement_hero
        runtime.professions[replacement_agent_id] = int(module.Profession.Paragon)
        runtime.bars[replacement_agent_id] = _role_bar(runtime, module, module.CleansingRole.HEROIC_REFRAIN)

    runtime.ready = True
    runtime.loading = False
    upkeeper.main()
    refreshed = context.GetSnapshot()

    assert refresh_calls == 3
    assert (
        not refreshed.supported_composition_proven
    ), f"{replacement} replacement during an invalid period must not inherit prior ACTIVE proof; {refreshed}"
    assert refreshed.composition.status is module.CompositionStatus.FALLBACK


def test_local_character_switch_invalidates_all_old_build_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    baseline = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.set_identity(12, "mesmer@example.test", "Mesmer B")
    for hero in runtime.heroes:
        hero.owner_player_id = runtime.login_number
    switched = context.Refresh()

    assert baseline.supported_composition_proven
    assert switched.character_identity == ("mesmer@example.test", "Mesmer B")
    assert not switched.supported_composition_proven
    assert all(
        member.role is module.CleansingRole.UNKNOWN for member in switched.members
    ), f"old character baselines must not cross a character switch; observed={switched.members}"


def test_runtime_read_failure_clears_snapshot_and_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    supported = context.Refresh()
    corelib = sys.modules["Py4GWCoreLib"]
    original_party = corelib.GLOBAL_CACHE.Party
    failing_party = types.SimpleNamespace(
        IsPartyLoaded=lambda: True,
        GetPlayers=lambda: (_ for _ in ()).throw(RuntimeError("party read failed")),
        GetHeroes=original_party.GetHeroes,
        GetHenchmen=original_party.GetHenchmen,
        GetPartySize=original_party.GetPartySize,
        Players=original_party.Players,
        Heroes=original_party.Heroes,
    )
    monkeypatch.setattr(corelib.GLOBAL_CACHE, "Party", failing_party)

    failed = context.Refresh()

    assert supported.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert failed.members == () and not failed.ready, f"failed reads must publish no stale roles; observed={failed}"
    assert "read failed" in failed.reason


def test_unchanged_refresh_keeps_revision_and_member_lookup_is_from_snapshot(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    first = context.Refresh()
    second = context.Refresh()

    assert (
        second.revision == first.revision
    ), f"unchanged evidence should not publish a new revision: {first} -> {second}"
    assert second.get_member(first.members[0].identity) == first.members[0]
    assert context.GetMember(first.members[0].identity) == first.members[0]
