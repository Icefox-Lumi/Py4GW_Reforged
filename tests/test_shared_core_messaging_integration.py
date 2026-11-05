"""Combined candidate router over pinned retained runtime, with inert host sinks.

No production initializer runs. Queue callbacks remain deferred through their real
owners; these tests distinguish submission from observed template verification.
"""

# pyright: strict

from __future__ import annotations

import ast
import re
import sys
from collections import deque
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from math import isfinite
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import TypedDict
from typing import cast

import pytest
from test_shared_core_package1_consumers import HTM
from test_shared_core_package1_consumers import Source
from test_shared_core_package1_consumers import retained_world as retained_world
from test_shared_core_package2_dispatch import MESSAGING_PATH
from test_shared_core_package2_dispatch import RETAINED_UPKEEPER
from test_shared_core_package2_dispatch import Timer
from test_shared_core_package2_dispatch import make_message
from test_shared_core_package2_dispatch import read_source
from test_shared_core_package2_dispatch import retained_env as retained_env_fixture
from test_shared_core_package2_dispatch import selected

retained_env = retained_env_fixture

UTILS = Source("Py4GWCoreLib/py4gwcorelib_src/Utils.py", "066cd34610c1f78da9a042a91d593670a655edc2")
PARTY = Source("Py4GWCoreLib/GlobalCache/PartyCache.py", "8ae8573aa43399804e0764d3c69a3d87468aa42c")
PLAYER = Source("Py4GWCoreLib/Player.py", "05037041f94da16430fb3ac81c551bb8c15acce7")
SKILLBAR = Source("Py4GWCoreLib/GlobalCache/SkillbarCache.py", "d66ffa9f402865c67616b6acd40d879cb1bd838a")
QUEUES = Source("Py4GWCoreLib/py4gwcorelib_src/ActionQueue.py", "3cea63654d2eb8198468a7c20da88a8bf9269b61")
NAMES = Source(
    "Py4GWCoreLib/py4gwcorelib_src/system_settings/name_obfuscation/resolve.py",
    "144d3443bbcd96fde56f2629d3ba98b355a632ec",
)
MANAGER = Source("Py4GWCoreLib/py4gwcorelib_src/WidgetManager.py", "75af3bdda417adb8418b4807b87e29a2de068667")
ACCOUNT_COPY = Source(
    "Py4GWCoreLib/py4gwcorelib_src/system_settings/account_copy.py",
    "ec712ba73d1c161601df39479029e042f0f8cb96",
)


def module_at(monkeypatch: pytest.MonkeyPatch, name: str, **namespace: Any) -> Any:
    module = ModuleType(name)
    module.__dict__.update(namespace)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def pinned(source: Source, names: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, **namespace: Any) -> Any:
    return selected(read_source(source), f"{source.path}@{source.blob}", names, monkeypatch, namespace)


class EligibleTimer(Timer):
    def IsExpired(self) -> bool:
        return self.elapsed


def complete(generator: Any, limit: int = 20) -> None:
    for _ in range(limit):
        try:
            next(generator)
        except StopIteration:
            return
    pytest.fail("generator did not terminate within bounded offline steps")


def install_htm(state: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    utils = pinned(
        UTILS,
        ("Utils.base64_to_bin64", "Utils.bin64_to_dec", "Utils.dec_to_bin64", "Utils.bin64_to_base64"),
        monkeypatch,
    )
    module_at(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.Utils", Utils=utils.Utils)
    text = read_source(HTM)
    names: list[str] = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign):
            names.extend(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id.startswith("PLAYER_TEMPLATE_")
            )
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (
            node.name in ("PlayerTemplateSpec", "parse_player_template_code", "normalize_player_attributes")
            or node.name.startswith(
                (
                    "_player_template_",
                    "normalize_player_template_",
                    "player_template_",
                    "encode_player_template_",
                    "decode_player_template_",
                    "valid_player_template_",
                    "get_player_template_",
                    "cache_player_template_",
                    "validate_player_template_result",
                )
            )
        ):
            names.append(node.name)
    runtime = selected(
        text,
        f"{HTM.path}@{HTM.blob}",
        tuple(names),
        monkeypatch,
        dict(re=re, monotonic=lambda: state.now, isfinite=isfinite),
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.modular.hero_team_manager", runtime)
    binary = "".join(
        utils.Utils.dec_to_bin64(value, width)
        for value, width in (
            (14, 4),
            (0, 4),
            (0, 2),
            (1, 4),
            (0, 4),
            (0, 4),
            (0, 4),
            (0, 4),
            *((skill, 8) for skill in range(1, 9)),
            (0, 1),
        )
    )
    state.code = utils.Utils.bin64_to_base64(binary)
    state.spec = runtime.parse_player_template_code(state.code)
    assert state.spec is not None, "actual retained parser and Utils must accept the test template"
    return runtime


def install_queues(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    queue_module = pinned(
        QUEUES,
        ("ActionQueue", "ActionQueueNode", "ActionQueueManager"),
        monkeypatch,
        deque=deque,
        datetime=datetime,
        Timer=EligibleTimer,
    )
    state.QueueManager = queue_module.ActionQueueManager
    state.actions = state.QueueManager()

    def native_chat(command: str) -> None:
        state.native.append(("chat", command, state.map_id, state.character))

    player = pinned(
        PLAYER,
        ("Player.player_instance", "Player.SendChatCommand"),
        monkeypatch,
        PyPlayer=SimpleNamespace(PyPlayer=lambda: SimpleNamespace(SendChatCommand=native_chat)),
        ActionQueueManager=state.QueueManager,
    ).Player
    for name in ("GetAccountEmail", "GetName", "IsPlayerLoaded", "GetAgentID", "GetInstanceUptime", "GetLoginNumber"):
        setattr(player, name, staticmethod(getattr(state.player, name)))
    state.player = player
    resolver = pinned(NAMES, ("require_real_name",), monkeypatch)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.py4gwcorelib_src.system_settings.name_obfuscation.resolve", resolver)

    def resolve_name(name: str) -> str:
        return name

    def agent_for_login(login: int) -> int:
        return 123 if login == 102 else 321

    def name_for_login(login: int) -> str:
        return state.character if login == 102 else "Sender"

    module_at(monkeypatch, "PyNameObfuscator", resolve_name=resolve_name)
    state.native_party = SimpleNamespace(
        party_id=10,
        players=[SimpleNamespace(login_number=101), SimpleNamespace(login_number=102)],
        heroes=[],
        henchmen=[],
        others=[],
        party_player_count=2,
        party_hero_count=0,
        party_henchman_count=0,
        party_size=2,
        is_party_loaded=True,
        is_party_leader=True,
        GetAgentIDByLoginNumber=agent_for_login,
        GetPlayerNameByLoginNumber=name_for_login,
    )
    party = pinned(
        PARTY,
        ("PartyCache",),
        monkeypatch,
        PyParty=SimpleNamespace(PyParty=lambda: state.native_party),
        Player=player,
        Map=state.map,
        Party=SimpleNamespace(),
        ActionQueueManager=state.QueueManager,
    )
    state.cache.Party = party.PartyCache(state.actions)

    def native_load(code: str) -> None:
        state.native.append(("template", code, state.map_id, state.character))

    def native_skill(slot: int) -> SimpleNamespace:
        return SimpleNamespace(id=SimpleNamespace(id=slot if state.matches else 0))

    def native_decode(_code: str) -> dict[str, Any]:
        return dict(profession=1, secondary_profession=0, skills=list(range(1, 9)), attributes=[])

    state.native_skillbar = SimpleNamespace(
        GetContext=lambda: None,
        GetSkill=native_skill,
        LoadSkillTemplate=native_load,
    )
    state.skillbar_module = module_at(
        monkeypatch,
        "PySkillbar",
        Skillbar=lambda: state.native_skillbar,
        encode_skill_template=lambda: state.code if state.matches else "",
        decode_skill_template=native_decode,
    )
    skillbar = pinned(
        SKILLBAR,
        ("SkillbarCache.__init__", "SkillbarCache.LoadSkillTemplate"),
        monkeypatch,
        PySkillbar=state.skillbar_module,
        ActionQueueManager=state.QueueManager,
    )
    state.cache.SkillBar = skillbar.SkillbarCache(state.actions)


def install_router(state: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    source = MESSAGING_PATH.read_text(encoding="utf-8-sig")
    names: list[str] = []
    explicit = {
        "_HTMNormalizedTemplate",
        "_HTMCoroutineSink",
        "InviteToParty",
        "PartyStateQuery",
        "HeroTeamPlayerSkillTemplateRequest",
        "HeroTeamPlayerSkillTemplateResult",
        "_extra_data",
        "_c_wchar_array_to_str",
        "AccountSettingsSync",
        "AccountSettingsSyncResult",
        "PickUpLoot",
        "HeroAIoptions",
        "SnapshotHeroAIOptions",
        "RestoreHeroAISnapshot",
        "DisableHeroAIOptions",
        "EnableHeroAIOptions",
        "HealStaleHeroAISnapshot",
        "_hero_ai_options_all_disabled",
        "_has_active_hero_ai_suspending_message",
        "_queue_widget_enable",
        "_process_pending_widget_enables",
        "MerchantRules",
        "ProcessMessages",
        "main",
        "on_disable",
    }
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (
            node.name in explicit
            or node.name.startswith(
                (
                    "_hero_team_player_template_",
                    "_party_state_",
                    "_guarded_party_",
                    "_cache_party_state_",
                    "_send_party_state_",
                    "_merchant_rules_",
                    "_MerchantRules",
                    "_queue_merchant_rules_",
                    "_reconcile_merchant_rules_",
                )
            )
        ):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
                and (
                    target.id.startswith(("_PARTY_STATE_", "_PARTY_INVITE_"))
                    or target.id in ("_MESSAGE_TYPE_OPTIONS", "_HERO_AI_SUSPENDING_COMMANDS", "_HTMSendMessage")
                )
            )
    namespace: dict[str, Any] = dict(cast(dict[str, Any], vars(state.messaging)))
    namespace.update(
        TypedDict=TypedDict,
        GLOBAL_CACHE=state.cache,
        Player=state.player,
        Map=state.map,
        Routines=state.routines,
        time=SimpleNamespace(monotonic=lambda: state.now),
        Agent=state.agent,
        ActionQueueManager=state.QueueManager,
        hero_ai_snapshots={},
        SHMEM_MAX_NUMBER_OF_SKILLS=8,
        Range=SimpleNamespace(Earshot=SimpleNamespace(value=1000)),
        datetime=datetime,
        timezone=timezone,
        post_loot_lock=noop,
        clear_loot_lock=noop,
        LootFilters=sys.modules["Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters"].__dict__["LootFilters"],
    )

    def is_enabled(_name: str) -> bool:
        return False

    def enable(name: str) -> None:
        state.events.append(("enabled", name))

    namespace.update(
        _pending_widget_enables=[],
        get_widget_handler=lambda: SimpleNamespace(is_widget_enabled=is_enabled, enable_widget=enable),
    )
    return selected(source, str(MESSAGING_PATH), tuple(names), monkeypatch, namespace)


@pytest.fixture
def combined(retained_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    state = retained_env
    state.now = 10.0
    state.native = []
    state.character = "Receiver"
    state.matches = False
    state.loading = False
    state.cinematic = False
    state.player.GetName = lambda: state.character
    state.player.GetLoginNumber = lambda: 102
    state.map.GetRegion = lambda: (0, "region")
    state.map.GetDistrict = lambda: 1
    state.map.GetLanguage = lambda: (0, "language")
    state.map.IsMapLoading = lambda: state.loading
    state.map.IsInCinematic = lambda: state.cinematic

    def native_professions(_agent: int) -> tuple[int, int]:
        return (1, 0)

    def native_attributes(_agent: int) -> list[Any]:
        return []

    state.agent = SimpleNamespace(GetProfessionIDs=native_professions, GetAttributes=native_attributes)
    for index in (0, 1):
        account = state.world.table.AccountData[index]
        account.LastUpdated = state.world.clock.frame
        account.AgentPartyData.PartyID = 10
        account.AgentData.LoginNumber = 101 + index
        account.AgentData.CharacterName = "Sender" if index == 0 else "Receiver"
        account.AgentData.Map.MapID = 1
        account.AgentData.Map.Region = 0
        account.AgentData.Map.District = 1
        account.AgentData.Map.Language = 0
    state.htm = install_htm(state, monkeypatch)
    install_queues(state, monkeypatch)
    state.messaging = install_router(state, monkeypatch)
    configuration = SimpleNamespace(
        action_queue_manager=state.actions, overlay=SimpleNamespace(UpkeepTextures=lambda: None)
    )
    for name in ("action", "transition", "loot", "merchant", "salvage", "identify", "fast"):
        setattr(configuration, f"throttle_{name}_queue", EligibleTimer())
    state.scheduler = pinned(
        RETAINED_UPKEEPER,
        ("main",),
        monkeypatch,
        GLOBAL_CACHE=state.cache,
        HOTKEY_MANAGER=SimpleNamespace(update=lambda: None),
        Routines=state.routines,
        Map=state.map,
        widget_config=configuration,
    ).main
    return state


def request(state: Any, index: int = 0, request_id: str = "a" * 32) -> Any:
    row = make_message(state, index=index, request=request_id)
    row.Command = state.world.commands.HeroTeamPlayerSkillTemplateRequest
    row.Timestamp = state.world.clock.frame
    row.Params[0] = 1
    row.Params[1] = len(state.code)
    row.ExtraData[1].value = state.code
    row.ExtraData[2].value = state.character
    row.ExtraData[3].value = state.htm.encode_player_template_guard((1, 0, 1, 0), 10, 101)
    return row


def result_codes(state: Any) -> list[str]:
    return [
        state.messaging._extra_data(row)[1]
        for row in state.world.table.Inbox
        if row.Active and row.Command == state.world.commands.HeroTeamPlayerSkillTemplateResult
    ]


def pending(state: Any) -> int:
    return len(state.actions.GetQueue("ACTION").action_queue.queue)


def finish_applied(state: Any, generator: Any) -> None:
    state.actions.ProcessQueue("ACTION")
    state.matches = True
    next(generator)
    state.now += 0.11
    complete(generator)


def test_duplicate_a_keeps_claim_competing_b_busy_original_releases_once(combined: Any) -> None:
    state = combined
    first = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, request(state))
    assert next(first, "terminated") != "terminated", state.logs
    runtime = state.messaging._hero_team_player_template_runtime()
    token = runtime["_active_request_owner_token"]
    complete(state.messaging.HeroTeamPlayerSkillTemplateRequest(5, request(state, 5)))
    assert runtime["_active_request_owner_token"] is token
    assert runtime["active_request_id"] == "a" * 32
    complete(state.messaging.HeroTeamPlayerSkillTemplateRequest(10, request(state, 10, "b" * 32)))
    assert result_codes(state) == ["duplicate_request", "target_busy"]
    assert pending(state) == 1 and not state.native
    finish_applied(state, first)
    assert result_codes(state) == ["duplicate_request", "target_busy", "applied"]
    assert runtime["active_request_id"] == ""
    assert runtime.get("_active_request_owner_token") is None
    first.close()
    assert len(state.native) == 1


@pytest.mark.parametrize("failure", ["protocol", "stale", "malformed_guard", "wrong_character", "timeout", "close"])
def test_acquisition_failure_cleanup_and_deferred_callback_survival(combined: Any, failure: str) -> None:
    state = combined
    row = request(state)
    runtime = state.messaging._hero_team_player_template_runtime()
    sentinel = object()
    if failure in ("protocol", "stale"):
        runtime.update(active_request_id="a" * 32, _active_request_owner_token=sentinel)
        if failure == "protocol":
            row.Params[0] = 9
        else:
            row.Timestamp = 1
    elif failure == "malformed_guard":
        row.ExtraData[3].value = "bad"
    elif failure == "wrong_character":
        row.ExtraData[2].value = "Different"
    generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, row)
    if failure in ("timeout", "close"):
        next(generator)
        assert pending(state) == 1 and not state.native
        if failure == "close":
            generator.close()
        else:
            state.now += 2.1
            complete(generator)
        assert pending(state) == 1
        state.map_id = 9
        state.character = "Changed"
        state.actions.ProcessQueue("ACTION")
        assert state.native == [("template", state.code, 9, "Changed")]
    else:
        complete(generator)
        assert pending(state) == 0 and not state.native
    if failure in ("protocol", "stale"):
        assert runtime["_active_request_owner_token"] is sentinel
        assert runtime["active_request_id"] == "a" * 32
    else:
        assert runtime["active_request_id"] == ""
        assert runtime.get("_active_request_owner_token") is None
    assert not row.Active
    expected = {
        "protocol": "invalid_request",
        "stale": "stale_request",
        "malformed_guard": "invalid_request",
        "wrong_character": "wrong_character",
        "timeout": "skill_mismatch",
    }
    assert result_codes(state) == ([] if failure == "close" else [expected[failure]])


def test_expired_replay_same_id_successor_survives_old_cleanup_distinct_rows(combined: Any) -> None:
    state = combined
    first_row = request(state, 0)
    first = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, first_row)
    next(first)
    runtime = state.messaging._hero_team_player_template_runtime()
    first_token = runtime["_active_request_owner_token"]
    state.now += 5.1
    second_row = request(state, 1)
    second = state.messaging.HeroTeamPlayerSkillTemplateRequest(1, second_row)
    next(second)
    successor = runtime["_active_request_owner_token"]
    assert successor is not first_token
    complete(first)
    assert runtime["_active_request_owner_token"] is successor
    assert runtime["active_request_id"] == "a" * 32
    assert not first_row.Active and second_row.Active and second_row.Running
    second.close()
    assert runtime["active_request_id"] == "" and pending(state) == 2


@pytest.mark.parametrize("change", ["map", "character", "party"])
def test_queued_template_context_checked_after_stable_match_not_at_native_sink(combined: Any, change: str) -> None:
    state = combined
    generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, request(state))
    next(generator)
    if change == "map":
        state.map_id = 2
    elif change == "character":
        state.character = "Changed"
    else:
        state.native_party.party_id = 99
    next(generator)
    assert not result_codes(state), "unmatched verification iteration has no context rejection"
    assert pending(state) == 1 and not state.native
    state.actions.ProcessQueue("ACTION")
    assert len(state.native) == 1, "native callback has no per-request final guard"
    state.matches = True
    next(generator)
    state.now += 0.11
    complete(generator)
    assert result_codes(state) == [{"map": "wrong_map", "character": "wrong_character", "party": "wrong_party"}[change]]


def test_already_matching_template_is_verified_without_enqueue(combined: Any) -> None:
    state = combined
    state.matches = True
    generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, request(state))
    next(generator)
    assert pending(state) == 0
    state.now += 0.11
    complete(generator)
    assert result_codes(state) == ["already_matches"] and not state.native


def test_real_string_invitation_uses_two_deferred_callbacks_one_owner(combined: Any) -> None:
    state = combined
    state.cache.Party.Players.InvitePlayer("Sender")
    assert state.cache.Party._action_queue_manager is state.cache.SkillBar._action_queue_manager is state.QueueManager()
    assert pending(state) == 1 and not state.native
    state.actions.GetQueue("ACTION").action_queue_timer.elapsed = False
    assert not state.actions.ProcessQueue("ACTION")
    assert pending(state) == 1
    state.actions.GetQueue("ACTION").action_queue_timer.elapsed = True
    assert state.actions.ProcessQueue("ACTION")
    assert pending(state) == 1 and not state.native
    state.map_id = 99
    state.character = "Changed"
    assert state.actions.ProcessQueue("ACTION")
    assert state.native == [("chat", "invite Sender", 99, "Changed")]


def test_ordinary_invitation_reads_sender_name_after_existing_wait(combined: Any) -> None:
    state = combined
    row = make_message(state)
    row.Command = state.world.commands.InviteToParty
    generator = state.messaging.InviteToParty(0, row)
    assert next(generator) == 100 and pending(state) == 0
    state.world.table.AccountData[0].AgentData.CharacterName = "Renamed"
    assert next(generator) == 100 and pending(state) == 1
    state.world.table.AccountData[0].AgentData.CharacterName = "Later"
    complete(generator)
    state.actions.ProcessQueue("ACTION")
    assert not state.native
    state.actions.ProcessQueue("ACTION")
    assert state.native[0][1] == "invite Renamed"


@pytest.mark.parametrize("context", ["loading", "cinematic", "invalid", "valid"])
def test_upkeeper_coroutines_precede_clear_suspend_or_queue_execution(combined: Any, context: str) -> None:
    state = combined

    def enqueue() -> Generator[None, None, None]:
        state.events.append("coroutine")
        state.cache.Party.Players.InvitePlayer("Sender")
        yield

    state.cache.Coroutines.append(enqueue())
    state.loading = context == "loading"
    state.cinematic = context == "cinematic"
    state.party_ready = context not in ("invalid", "loading", "cinematic")
    state.scheduler()
    assert state.events[-1] == "coroutine" and not state.native
    if context in ("loading", "cinematic"):
        assert pending(state) == 0
    elif context == "invalid":
        assert pending(state) == 1 and not state.actions.GetHistory("ACTION")
    else:
        assert pending(state) == 1 and len(state.actions.GetHistory("ACTION")) == 1
    state.loading = state.cinematic = False
    state.party_ready = True
    state.scheduler()
    state.scheduler()
    assert bool(state.native) == (context in ("invalid", "valid"))


@pytest.mark.parametrize("invalid", ["none", "map", "character", "party"])
def test_guarded_invitation_admission_and_later_unguarded_native_submission(combined: Any, invalid: str) -> None:
    state = combined
    state.native_party.players = [SimpleNamespace(login_number=102)]
    state.native_party.party_player_count = state.native_party.party_size = 1
    row = make_message(state)
    row.Command = state.world.commands.InviteToParty
    for slot, value in enumerate(("party_invite_guard", "guard-request", "Receiver", "1,0,1,0")):
        row.ExtraData[slot].value = value
    if invalid == "map":
        state.map_id = 3
    elif invalid == "character":
        state.character = "Changed"
    elif invalid == "party":
        state.native_party.heroes = [SimpleNamespace()]
        state.native_party.party_hero_count = 1
        state.native_party.party_size = 2
    complete(state.messaging.InviteToParty(0, row))
    replies = [candidate for candidate in state.world.table.Inbox if candidate.Active]
    assert len(replies) == 1
    outcome = state.messaging._extra_data(replies[0])[2]
    assert not state.native and not row.Active
    if invalid != "none":
        assert outcome == f"guard_failed: {invalid}_changed"
        assert pending(state) == 0
        return
    assert outcome == "reciprocal_invite_sent" and pending(state) == 1
    state.map_id = 7
    state.character = "Later"
    state.native_party.party_size = 4
    state.actions.ProcessQueue("ACTION")
    assert pending(state) == 1 and not state.native
    state.actions.ProcessQueue("ACTION")
    assert state.native == [("chat", "invite Sender", 7, "Later")]


def test_query_reply_result_correlation_and_three_reload_surviving_caches(
    combined: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = combined
    row = make_message(state)
    row.Command = state.world.commands.PartyStateQuery
    row.ExtraData[0].value = "party_state_request"
    row.ExtraData[1].value = "query-id"
    state.messaging.ProcessMessages()
    assert len(state.cache.Coroutines) == 1
    complete(state.cache.Coroutines.pop())
    reply_index, reply = next(
        (index, candidate) for index, candidate in enumerate(state.world.table.Inbox) if candidate.Active
    )
    assert state.messaging._extra_data(reply)[:3] == ("party_state_reply", "query-id", "Receiver")
    complete(state.messaging.PartyStateQuery(reply_index, reply))
    query_cache = state.messaging._party_state_query_cache()
    query = query_cache[(state.world.receiver.casefold(), "query-id")]
    assert query["party_id"] == 10 and query["player_count"] == 2
    assert query["map_signature"] == (1, 0, 1, 0)
    active_cache = state.messaging._hero_team_player_template_runtime()
    active_cache["seen_request_ids"]["expired"] = state.now - 1
    state.matches = True
    generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, request(state))
    next(generator)
    state.now += 0.11
    complete(generator)
    result_index, result_row = next(
        (index, candidate) for index, candidate in enumerate(state.world.table.Inbox) if candidate.Active
    )
    complete(state.messaging.HeroTeamPlayerSkillTemplateResult(result_index, result_row))
    result_cache = state.htm._player_template_result_cache()
    result = state.htm.get_player_template_result(state.world.receiver.upper(), "a" * 32)
    kwargs = dict(
        request_id="a" * 32,
        expected_sender_email=state.world.receiver,
        expected_receiver_email=state.world.sender,
        sent_at=10.0,
        now=state.now,
        now_tick=state.world.clock.frame,
    )
    assert state.htm.validate_player_template_result(result, **kwargs) == ("success", "already_matches")
    kwargs["request_id"] = "b" * 32
    assert state.htm.validate_player_template_result(result, **kwargs)[0] == "invalid"
    reloaded = install_router(state, monkeypatch)
    reloaded_runtime = install_htm(state, monkeypatch)
    assert reloaded._party_state_query_cache() is query_cache
    assert reloaded._hero_team_player_template_runtime() is active_cache
    assert "expired" not in active_cache["seen_request_ids"]
    assert reloaded_runtime._player_template_result_cache() is result_cache
    assert reloaded_runtime.get_player_template_result(state.world.receiver, "a" * 32) is result


@pytest.mark.parametrize(
    "command",
    ["PartyStateQuery", "HeroTeamPlayerSkillTemplateRequest", "HeroTeamPlayerSkillTemplateResult", "MerchantRules"],
)
def test_candidate_routes_wait_for_permission_recovery_with_retained_consumers(combined: Any, command: str) -> None:
    state = combined
    row = request(state)
    row.Command = getattr(state.world.commands, command)
    if command == "PartyStateQuery":
        row.ExtraData[0].value = "party_state_request"
        row.ExtraData[1].value = "query"
    elif command == "HeroTeamPlayerSkillTemplateResult":
        row.ExtraData[1].value = "wrong_map"
    elif command == "MerchantRules":
        row.Params[0] = 2
    state.world.table.AccountData[1].IsolationGroupID = 2
    state.world.table.AccountData[1].AgentPartyData.PartyID = 11
    before = bytes(state.world.table)
    state.messaging.ProcessMessages()
    assert not state.cache.Coroutines and not state.events
    assert bytes(state.world.table) == before
    state.world.table.AccountData[1].IsolationGroupID = 1
    state.world.table.AccountData[1].AgentPartyData.PartyID = 10
    state.messaging.ProcessMessages()
    assert state.events == ["received"] and len(state.cache.Coroutines) == 1
    queued = state.cache.Coroutines.pop()
    if command == "MerchantRules":
        assert isinstance(queued, state.messaging._MerchantRulesDispatchReceipt)
        fsm = state.FSM("combined-retained-receipt")
        fsm.AddSelfManagedYieldStep("receipt", lambda: queued)
        fsm.start()
        fsm.update()
        fsm.reset()
        assert not row.Active
    elif command == "HeroTeamPlayerSkillTemplateRequest":
        next(queued)
        assert pending(state) == 1
        queued.close()
    else:
        complete(queued)
        assert not row.Active
    assert (
        int(state.world.commands.PartyStateQuery),
        int(state.world.commands.HeroTeamPlayerSkillTemplateRequest),
        int(state.world.commands.HeroTeamPlayerSkillTemplateResult),
    ) == (74, 75, 76)


def install_account_service(state: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    def flush() -> bool:
        state.events.append("flush")
        return True

    def reload_and_apply() -> bool:
        state.events.append("reload/apply")
        return True

    spec = SimpleNamespace(
        settings_documents=("document",), json_documents=(), flush_local=flush, reload_and_apply=reload_and_apply
    )

    def get_spec(setting: str) -> Any:
        return spec if setting == "setting" else None

    names = (
        "_PREPARE",
        "_APPLY",
        "_CANCEL",
        "_RESULT_OK",
        "_TRANSACTION_TIMEOUT_SECONDS",
        "_LOCK_TIMEOUT_SECONDS",
        "TargetCopyState",
        "CopyTransaction",
        "PreparedCopy",
        "AccountCopyService.__init__",
        "AccountCopyService._document_tokens",
        "AccountCopyService._send_sync",
        "AccountCopyService._send_result",
        "AccountCopyService._extra_data",
        "AccountCopyService.handle_sync_message",
        "AccountCopyService.handle_result_message",
        "AccountCopyService.tick",
        "AccountCopyService._release_prepare",
        "get_copy_service",
    )
    runtime = pinned(
        ACCOUNT_COPY,
        names,
        monkeypatch,
        time=SimpleNamespace(monotonic=lambda: state.now),
        get_spec=get_spec,
        _service=None,
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.py4gwcorelib_src.system_settings.account_copy", runtime)
    module_at(monkeypatch, "Py4GWCoreLib.Player", Player=state.player)
    monkeypatch.setattr(sys.modules["Py4GWCoreLib"], "SharedCommandType", state.world.commands, raising=False)
    return runtime


@pytest.mark.parametrize("command", ["AccountSettingsSync", "AccountSettingsSyncResult"])
def test_account_settings_handlers_keep_exception_filter_and_real_service(
    combined: Any, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    state = combined
    runtime = install_account_service(state, monkeypatch)
    service = runtime.get_copy_service()
    row = make_message(state)
    row.Command = getattr(state.world.commands, command)
    row.ExtraData[0].value = "copy-id"
    row.ExtraData[1].value = "setting"
    row.Params[0] = 1
    row.Params[1] = 1
    state.world.table.AccountData[1].IsIsolated = True
    state.world.table.AccountData[0].IsolationGroupID = 2
    state.world.table.AccountData[1].AgentPartyData.PartyID = 11
    assert row.Command not in state.messaging._MESSAGE_TYPE_OPTIONS
    assert state.world.table.GetAllMessages() == []
    assert state.world.table.GetNextMessage(state.world.receiver)[0] == 0
    if command == "AccountSettingsSyncResult":
        target = runtime.TargetCopyState(state.world.sender, loaded=True)
        service.transaction = runtime.CopyTransaction("copy-id", "setting", (), {state.world.sender: target})
    else:
        target = None
    state.messaging.ProcessMessages()
    assert not row.Active and not state.cache.Coroutines
    if command == "AccountSettingsSync":
        assert state.events == ["received", "flush"]
        assert service._prepared_by_setting == {"setting": "copy-id"}
        state.now += 12.1
        state.messaging.main()
        assert service._prepared == {} and service._prepared_by_setting == {}
    else:
        assert target is not None
        assert target.status == "Applying"
        state.now += 8.1
        state.messaging.main()
        assert target.status == "Timed out"


@pytest.mark.parametrize("failure", ["empty", "lookup_exception", "claimed_exception"])
def test_loot_wider_finally_restores_options_and_retires_row(
    combined: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = combined
    row = make_message(state)
    row.Command = state.world.commands.PickUpLoot
    options = state.world.table.GetHeroAIOptionsFromEmail(state.world.receiver)
    options.Following = True
    options.Combat = False
    initial = bytes(options)
    locks: list[int] = []

    def loot(_range: int) -> list[int]:
        if failure == "lookup_exception":
            raise RuntimeError("inert loot lookup failed")
        return [42] if failure == "claimed_exception" else []

    def invalid(_item: int) -> bool:
        raise RuntimeError("inert item read failed")

    def claim(item: int) -> int:
        locks.append(item)
        return 0

    def clear(item: int) -> None:
        locks.remove(item)

    def item_owner(_item: int) -> int:
        return 0

    monkeypatch.setattr(state.messaging, "LootFilters", lambda: SimpleNamespace(GetLootArray=loot))
    monkeypatch.setattr(state.messaging, "post_loot_lock", claim)
    monkeypatch.setattr(state.messaging, "clear_loot_lock", clear)
    state.cache.Inventory = SimpleNamespace(GetFreeSlotCount=lambda: 1)
    state.agent.GetItemAgentOwnerID = item_owner
    state.agent.IsValid = invalid
    generator = state.messaging.PickUpLoot(0, row)
    if failure == "empty":
        complete(generator)
    else:
        with pytest.raises(RuntimeError, match="inert"):
            complete(generator)
    assert bytes(options) == initial
    assert not state.messaging.hero_ai_snapshots and not row.Active and not locks


@pytest.mark.parametrize("operation", ["pause", "disable", "reload"])
def test_retained_widget_manager_pause_disable_reload_preserve_router_lifecycle(
    combined: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    state = combined
    row = make_message(state)
    state.messaging.ProcessMessages()
    receipt = state.cache.Coroutines[0]
    paused: list[int] = []
    names = (
        "_bump_widgets_revision",
        "Widget.enabled",
        "Widget.is_paused",
        "Widget.pause",
        "Widget.PauseCallbacks",
        "Widget.disable",
        "WidgetHandler.prepare_discover",
        "WidgetHandler.discover",
        "WidgetHandler.reload_widgets",
    )
    runtime = pinned(
        MANAGER,
        names,
        monkeypatch,
        PySystem=state.world.system,
        PyCallback=SimpleNamespace(PyCallback=SimpleNamespace(PauseById=paused.append)),
        _widgets_revision=0,
    )
    widget = runtime.Widget()
    widget.__dict__.update(
        _Widget__enabled=True,
        _Widget__paused=False,
        on_pause=None,
        on_disable=state.messaging.on_disable,
        module=state.messaging,
        update_callback_id=1,
        draw_callback_id=2,
        main_callback_id=3,
        folder_script_name="Messaging",
    )
    if operation == "pause":
        widget.pause()
        assert widget.enabled and widget.is_paused and row.Active
        assert receipt in state.cache.Coroutines
        widget.disable()
    elif operation == "disable":
        widget.disable()
    else:
        handler = runtime.WidgetHandler()
        handler.widgets = {"Messaging": widget}
        handler.discovered = True
        handler.ini_applied = True
        scans: list[bool] = []
        handler._scan_widget_folders = lambda: scans.append(not row.Active)
        handler.reload_widgets()
        assert scans == [True] and not handler.widgets and handler.widget_initialized
    assert paused[:3] == [1, 2, 3]
    assert not widget.enabled and not row.Active
    assert receipt.terminal
    state.scheduler()
    assert receipt not in state.cache.Coroutines


@pytest.mark.parametrize("phase", ["before_acquisition", "after_enqueue"])
def test_external_boundary_exception_cleanup_is_acquisition_selective(
    combined: Any, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    state = combined
    row = request(state)
    runtime = state.messaging._hero_team_player_template_runtime()
    old_token = object()
    if phase == "before_acquisition":
        runtime.update(active_request_id="a" * 32, _active_request_owner_token=old_token)
        original = state.world.table.MarkMessageAsRunning

        def fail_after_mark(*args: Any) -> None:
            original(*args)
            raise RuntimeError("inert shared-memory boundary failure")

        monkeypatch.setattr(state.world.table, "MarkMessageAsRunning", fail_after_mark)
    else:
        raised = False

        def fail_after_queue() -> float:
            nonlocal raised
            if pending(state) and not raised:
                raised = True
                raise RuntimeError("inert clock failure after enqueue")
            return state.now

        monkeypatch.setattr(state.messaging.time, "monotonic", fail_after_queue)
    complete(state.messaging.HeroTeamPlayerSkillTemplateRequest(0, row))
    assert result_codes(state) == ["target_state_unavailable"]
    assert not row.Active and not state.native
    if phase == "before_acquisition":
        assert runtime["_active_request_owner_token"] is old_token
        assert runtime["active_request_id"] == "a" * 32 and pending(state) == 0
    else:
        assert runtime["active_request_id"] == ""
        assert runtime.get("_active_request_owner_token") is None and pending(state) == 1
        state.actions.ProcessQueue("ACTION")
        assert state.native == [("template", state.code, 1, "Receiver")]


def test_lazy_htm_import_gate_is_separate_from_router_and_party_query(
    combined: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = combined
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.modular.hero_team_manager", None)
    router = install_router(state, monkeypatch)
    query = make_message(state)
    query.Command = state.world.commands.PartyStateQuery
    query.ExtraData[0].value = "party_state_request"
    query.ExtraData[1].value = "lazy-query"
    complete(router.PartyStateQuery(0, query))
    assert not query.Active
    row = request(state, 10)
    generator = router.HeroTeamPlayerSkillTemplateRequest(10, row)
    with pytest.raises(ImportError):
        next(generator)
    assert row.Active and not row.Running and pending(state) == 0
    assert router._hero_team_player_template_runtime()["active_request_id"] == ""


def test_main_orders_real_reconcile_heal_enable_dispatch_and_service_pump(
    combined: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = combined
    runtime = install_account_service(state, monkeypatch)
    service = runtime.get_copy_service()
    order: list[str] = []

    def observe(owner: Any, name: str) -> None:
        original = getattr(owner, name)

        def invoke(*args: Any, **kwargs: Any) -> Any:
            order.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, invoke)

    for name in (
        "_reconcile_merchant_rules_dispatches",
        "HealStaleHeroAISnapshot",
        "_process_pending_widget_enables",
        "ProcessMessages",
    ):
        observe(state.messaging, name)
    observe(service, "tick")
    state.messaging._queue_widget_enable("bounded-test-widget")
    state.messaging.main()
    assert order == [
        "_reconcile_merchant_rules_dispatches",
        "HealStaleHeroAISnapshot",
        "_process_pending_widget_enables",
        "ProcessMessages",
        "tick",
    ]
    assert state.events == [("enabled", "bounded-test-widget")]


def test_replay_expiry_preserves_cache_identity_nonstring_keys_and_float_semantics(combined: Any) -> None:
    state = combined
    runtime = state.messaging._hero_team_player_template_runtime()
    seen = cast(dict[object, object], runtime["seen_request_ids"])
    token = object()
    runtime.update(active_request_id="existing-owner", _active_request_owner_token=token)

    class Expiry:
        def __init__(self, value: float) -> None:
            self.value = value
            self.calls = 0

        def __float__(self) -> float:
            self.calls += 1
            return self.value

    future = Expiry(state.now + 1.0)
    expired = Expiry(state.now - 1.0)
    nonfinite = Expiry(float("nan"))
    object_key = object()
    nan = float("nan")
    seen.update(
        {
            object_key: future,
            ("expired", 1): expired,
            7: state.now,
            8: state.now - 1.0,
            b"future": str(state.now + 1.0),
            None: nan,
            ("custom", "nan"): nonfinite,
            "positive_infinity": float("inf"),
            "negative_infinity": float("-inf"),
            "malformed": "not-a-number",
            "missing": None,
        }
    )
    assert state.messaging._hero_team_player_template_runtime() is runtime
    assert runtime["seen_request_ids"] is seen
    assert runtime["_active_request_owner_token"] is token
    assert runtime["active_request_id"] == "existing-owner"
    assert set(seen) == {object_key, b"future", None, ("custom", "nan"), "positive_infinity"}
    assert seen[object_key] is future and seen[None] is nan and seen[("custom", "nan")] is nonfinite
    assert seen[b"future"] == str(state.now + 1.0)
    assert seen["positive_infinity"] == float("inf")
    assert (future.calls, expired.calls, nonfinite.calls) == (1, 1, 1)


@pytest.mark.parametrize(
    "exception_type,pruned",
    [
        pytest.param(TypeError, True, id="type_error"),
        pytest.param(ValueError, True, id="value_error"),
        pytest.param(OverflowError, False, id="overflow_error"),
        pytest.param(RuntimeError, False, id="runtime_error"),
    ],
)
def test_replay_expiry_prunes_only_type_and_value_errors(
    combined: Any, exception_type: type[Exception], pruned: bool
) -> None:
    state = combined
    runtime = state.messaging._hero_team_player_template_runtime()
    seen = cast(dict[object, object], runtime["seen_request_ids"])
    token = object()
    runtime.update(active_request_id="a" * 32, _active_request_owner_token=token)
    failure = exception_type("inert expiry conversion failure")

    class Expiry:
        calls = 0

        def __float__(self) -> float:
            self.calls += 1
            raise failure

    expiry = Expiry()
    key = object()
    seen.update({("expired", "before"): state.now - 1.0, key: expiry, ("expired", "after"): state.now - 1.0})
    row = request(state)
    before = bytes(row)
    if pruned:
        assert state.messaging._hero_team_player_template_runtime() is runtime
        assert seen == {}
    else:
        generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, row)
        with pytest.raises(exception_type) as caught:
            next(generator)
        assert caught.value is failure
        assert seen == {key: expiry, ("expired", "after"): state.now - 1.0}
    assert expiry.calls == 1
    assert state.cache._hero_team_player_template_runtime is runtime and runtime["seen_request_ids"] is seen
    assert runtime["active_request_id"] == "a" * 32 and runtime["_active_request_owner_token"] is token
    assert bytes(row) == before and row.Active and not row.Running
    assert not result_codes(state) and pending(state) == 0 and not state.native


def test_template_enqueue_none_return_keeps_real_callback_deferred_and_verifies(
    combined: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = combined
    original = cast(Callable[[str], None], state.cache.SkillBar.LoadSkillTemplate)
    returned: list[None] = []

    def observe_enqueue(code: str) -> None:
        result = original(code)
        returned.append(result)
        return result

    monkeypatch.setattr(state.cache.SkillBar, "LoadSkillTemplate", observe_enqueue)
    row = request(state)
    generator = state.messaging.HeroTeamPlayerSkillTemplateRequest(0, row)
    next(generator)
    runtime = state.messaging._hero_team_player_template_runtime()
    token = runtime["_active_request_owner_token"]
    assert returned == [None] and pending(state) == 1 and not state.native
    assert row.Active and row.Running and not result_codes(state)
    state.actions.ProcessQueue("ACTION")
    assert state.native == [("template", state.code, 1, "Receiver")]
    assert pending(state) == 0 and not result_codes(state)
    assert runtime["_active_request_owner_token"] is token
    state.matches = True
    next(generator)
    state.now += 0.11
    complete(generator)
    assert result_codes(state) == ["applied"] and not row.Active
    assert runtime["active_request_id"] == "" and runtime.get("_active_request_owner_token") is None
    assert returned == [None] and len(state.native) == 1


def test_template_real_enqueue_exception_retires_row_and_releases_acquired_claim(
    combined: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = combined
    runtime = state.messaging._hero_team_player_template_runtime()
    seen = runtime["seen_request_ids"]
    action_node = state.actions.GetQueue("ACTION")
    monkeypatch.delitem(state.actions.queues, "ACTION")
    row = request(state)
    complete(state.messaging.HeroTeamPlayerSkillTemplateRequest(0, row))
    assert result_codes(state) == ["queue_dispatch_failed"]
    reply = next(candidate for candidate in state.world.table.Inbox if candidate.Active)
    assert state.messaging._extra_data(reply)[3].endswith(";Xqueue_exception")
    assert any("Queue 'ACTION' does not exist." in str(entry) for entry in state.logs)
    assert not row.Active and not state.native and not action_node.action_queue.queue
    assert runtime["active_request_id"] == "" and runtime.get("_active_request_owner_token") is None
    assert runtime["seen_request_ids"] is seen and "a" * 32 in seen
    assert seen["a" * 32] == state.now + state.htm.PLAYER_TEMPLATE_REQUEST_TTL_MS / 1000.0


@pytest.mark.parametrize("decoded_available", [False, True])
def test_template_observation_preserves_real_normalized_shapes_and_flags(
    combined: Any, monkeypatch: pytest.MonkeyPatch, decoded_available: bool
) -> None:
    state = combined
    state.matches = True

    def attributes(_agent: int) -> list[SimpleNamespace]:
        return [SimpleNamespace(attribute_id=0, level_base=5, level=7)]

    def decode(_code: str) -> dict[str, object] | None:
        if not decoded_available:
            return None
        return {"profession": "1", "secondary_profession": "0", "skills": list(range(1, 9)), "attributes": {"0": "5"}}

    monkeypatch.setattr(state.agent, "GetAttributes", attributes)
    monkeypatch.setattr(state.skillbar_module, "decode_skill_template", decode)
    observation = state.messaging._hero_team_player_template_observation(state.native_skillbar)
    assert observation["skill_ids"] == tuple(range(1, 9))
    assert isinstance(observation["skill_ids"], tuple)
    assert (observation["primary_profession_id"], observation["secondary_profession_id"]) == (1, 0)
    assert type(observation["primary_profession_id"]) is type(observation["secondary_profession_id"]) is int
    assert observation["base_attributes"] == {0: 5} and observation["effective_levels"] == {0: 7}
    assert observation["encoded"] == state.code and observation["error"] == ""
    normalized = observation["normalized"]
    if decoded_available:
        assert normalized == {
            "primary_profession_id": 1,
            "secondary_profession_id": 0,
            "skill_ids": tuple(range(1, 9)),
            "attributes": {0: 5},
        }
    else:
        assert observation["decoded"] is None and normalized is None
    signature = state.messaging._hero_team_player_template_signature(observation)
    assert signature == (
        tuple(range(1, 9)),
        1,
        0,
        ((0, 5),),
        (1, 0, tuple(range(1, 9)), ((0, 5),)) if decoded_available else None,
    )
    assert state.messaging._hero_team_player_template_flags(state.spec, observation) == {
        "skills": True,
        "professions": True,
        "attributes": False,
        "normalized": False,
        "raw": True,
    }


def test_typed_response_senders_preserve_real_wire_values_and_integer_receipts(combined: Any) -> None:
    state = combined
    snapshot = {
        "party_size": 2,
        "player_count": 2,
        "hero_count": 0,
        "henchman_count": 0,
        "map_signature": (1, 0, 1, 0),
        "party_id": 10,
        "party_position": 1,
        "is_party_leader": True,
        "is_loaded": True,
        "other_count": 0,
    }
    party_index = state.messaging._send_party_state_result(
        f" {state.world.sender} ", "party_state_reply", "wire-query", snapshot, character_name="Receiver"
    )
    assert type(party_index) is int and party_index >= 0
    party_row = state.world.table.Inbox[party_index]
    assert (party_row.SenderEmail, party_row.ReceiverEmail) == (state.world.receiver, state.world.sender)
    assert int(party_row.Command) == 74 and tuple(party_row.Params) == (2.0, 2.0, 0.0, 0.0)
    assert state.messaging._extra_data(party_row) == (
        "party_state_reply",
        "wire-query",
        "Receiver",
        "1,0,1,0;10;1;1;1;0",
    )
    state.matches = True
    observation = state.messaging._hero_team_player_template_observation(state.native_skillbar)
    flags = state.messaging._hero_team_player_template_flags(state.spec, observation)
    template_index = state.messaging._hero_team_player_template_send_result(
        f" {state.world.sender} ", " aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ", " APPLIED ", observation, flags, "none", 17
    )
    assert type(template_index) is int and template_index >= 0 and template_index != party_index
    template_row = state.world.table.Inbox[template_index]
    assert (template_row.SenderEmail, template_row.ReceiverEmail) == (state.world.receiver, state.world.sender)
    assert int(template_row.Command) == 76 and tuple(template_row.Params) == (1.0, 17.0, 1.0, 0.0)
    assert state.messaging._extra_data(template_row) == ("a" * 32, "applied", state.code, "v1;S1;P1;A1;N1;R1;Xnone")
    assert not state.native and pending(state) == 0
