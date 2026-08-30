# Impor# Necessary Imports
import json

import Py4GW        #Miscelanious functions and classes
import PyImGui     #ImGui wrapper
import PyMap       #Direct target-local map state
import PyParty      #Party functions and classes
import PyPlayer     #Direct target-local player state
import PySystem     #Target-local diagnostic logging and timing
from Py4GWCoreLib.Context import GWContext  #Read-only native party context diagnostics

# End Necessary Imports

module_name = "PyParty_DEMO"

# Create an instance of PyParty
party_instance = PyParty.PyParty()

# Variables to store input for interactive methods
hero_id_input = 0
henchman_id_input = 0
player_id_input = 0
x_pos_input = 0.0
y_pos_input = 0.0
hard_mode_flag = False
a_party_id_input = 0

PARTY_PROBE_TIMEOUT_MS = 2000
PARTY_PROBE_LOG_MODULE = "PyParty_DEMO.PartyRequestProbe"
PARTY_CONTEXT_LOG_MODULE = "PyParty_DEMO.PartyRequestContextProbe"
PARTY_PROBE_IDLE = "IDLE"
PARTY_PROBE_RUNNING = "RUNNING"
PARTY_PROBE_SUCCEEDED = "SUCCEEDED"
PARTY_PROBE_TIMED_OUT = "TIMED OUT"
PARTY_PROBE_FAILED = "FAILED"
party_context_snapshot_id = 0


def _party_probe_new_state(run_id=0):
    return {
        "run_id": run_id,
        "status": PARTY_PROBE_IDLE,
        "mode": "",
        "expected_a_party_id": None,
        "baseline": None,
        "last_state": None,
        "final_state": None,
        "last_signature": None,
        "armed_tick": None,
        "invoke_tick": None,
        "return_tick": None,
        "deadline_tick": None,
        "first_change_tick": None,
        "last_change_tick": None,
        "first_expected_tick": None,
        "poll_samples": 0,
        "native_return_type": None,
        "native_return_value": None,
        "native_exception": None,
        "failure_reason": None,
    }


party_probe_state = _party_probe_new_state()
party_probe_direct_native_proven = False
player_instance = PyPlayer.PyPlayer()


def _party_probe_error_text(error):
    return f"{type(error).__name__}: {error}"[:240]


def _party_probe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _party_probe_tick():
    try:
        return int(PySystem.get_tick_count64())
    except Exception:
        return 0


def _party_probe_log(event, **details):
    payload = {
        "probe": "PartyRequestProbe",
        "run": party_probe_state["run_id"],
        "event": event,
    }
    payload.update(details)
    try:
        PySystem.Console.Log(
            PARTY_PROBE_LOG_MODULE,
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
        )
    except Exception:
        # Diagnostics must not turn an unavailable target state into a demo crash.
        pass


def _party_probe_read_attr(owner, name, errors, default=None):
    try:
        return getattr(owner, name)
    except Exception as error:
        errors.append(f"{name}: {_party_probe_error_text(error)}")
        return default


def _party_probe_read_call(callable_value, label, errors, default=None):
    try:
        return callable_value()
    except Exception as error:
        errors.append(f"{label}: {_party_probe_error_text(error)}")
        return default


def _party_probe_read_optional_attr(owner, name, errors, default=None):
    """Read an optional diagnostic field without treating a missing field as corruption."""
    try:
        return getattr(owner, name)
    except AttributeError:
        return default
    except Exception as error:
        errors.append(f"{name}: {_party_probe_error_text(error)}")
        return default


def _party_probe_context_int(value, label, errors, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except Exception as error:
        errors.append(f"{label}: {_party_probe_error_text(error)}")
        return default


def _party_probe_context_int_list(value, label, errors):
    if value is None:
        return None
    try:
        return [int(item) for item in list(value)]
    except Exception as error:
        errors.append(f"{label}: {_party_probe_error_text(error)}")
        return None


def _party_probe_context_link(link, errors):
    """Capture only GW_TLink scalar fields; never follow its pointers."""
    if link is None:
        return None
    link_data = {
        "prev_link": _party_probe_context_int(
            _party_probe_read_attr(link, "prev_link", errors, None),
            "invite_link.prev_link",
            errors,
        ),
        "next_node": _party_probe_context_int(
            _party_probe_read_attr(link, "next_node", errors, None),
            "invite_link.next_node",
            errors,
        ),
    }
    try:
        link_data["is_linked"] = bool(link.IsLinked())
    except Exception as error:
        errors.append(f"invite_link.IsLinked: {_party_probe_error_text(error)}")
        link_data["is_linked"] = None
    return link_data


def _party_probe_context_player(member, index, errors):
    member_errors = []
    login_number = _party_probe_context_int(
        _party_probe_read_attr(member, "login_number", member_errors, None),
        "login_number",
        member_errors,
    )
    member_data = {
        "member_index": index,
        "party_position": _party_probe_context_int(
            _party_probe_read_optional_attr(member, "party_position", member_errors, None),
            "party_position",
            member_errors,
        ),
        "login_number": login_number,
        "agent_id": _party_probe_context_int(
            _party_probe_read_optional_attr(member, "agent_id", member_errors, None),
            "agent_id",
            member_errors,
        ),
        "called_target_id": _party_probe_context_int(
            _party_probe_read_attr(member, "called_target_id", member_errors, None),
            "called_target_id",
            member_errors,
        ),
        "state": _party_probe_context_int(
            _party_probe_read_attr(member, "state", member_errors, None),
            "state",
            member_errors,
        ),
        "is_connected": _party_probe_read_optional_attr(member, "is_connected", member_errors, None),
        "is_ticked": _party_probe_read_optional_attr(member, "is_ticked", member_errors, None),
    }
    if login_number is not None:
        resolved_agent_id = _party_probe_read_call(
            lambda login=login_number: party_instance.GetAgentIDByLoginNumber(login),
            "resolved agent id",
            member_errors,
            None,
        )
        resolved_name = _party_probe_read_call(
            lambda login=login_number: party_instance.GetPlayerNameByLoginNumber(login),
            "resolved character name",
            member_errors,
            None,
        )
        member_data["resolved_agent_id"] = _party_probe_context_int(
            resolved_agent_id,
            "resolved agent id",
            member_errors,
        )
        member_data["resolved_character_name"] = (
            None if resolved_name is None else str(resolved_name)
        )
    else:
        member_data["resolved_agent_id"] = None
        member_data["resolved_character_name"] = None
    if member_errors:
        member_data["read_errors"] = sorted(set(member_errors))
        errors.extend(f"player[{index}]: {error}" for error in member_data["read_errors"])
    return member_data


def _party_probe_context_hero(member, index, errors):
    member_errors = []
    member_data = {
        "member_index": index,
        "agent_id": _party_probe_context_int(
            _party_probe_read_attr(member, "agent_id", member_errors, None),
            "agent_id",
            member_errors,
        ),
        "owner_player_id": _party_probe_context_int(
            _party_probe_read_attr(member, "owner_player_id", member_errors, None),
            "owner_player_id",
            member_errors,
        ),
        "hero_id": _party_probe_context_int(
            _party_probe_read_attr(member, "hero_id", member_errors, None),
            "hero_id",
            member_errors,
        ),
        "h000C": _party_probe_context_int(
            _party_probe_read_attr(member, "h000C", member_errors, None),
            "h000C",
            member_errors,
        ),
        "h0010": _party_probe_context_int(
            _party_probe_read_attr(member, "h0010", member_errors, None),
            "h0010",
            member_errors,
        ),
        "level": _party_probe_context_int(
            _party_probe_read_attr(member, "level", member_errors, None),
            "level",
            member_errors,
        ),
    }
    if member_errors:
        member_data["read_errors"] = sorted(set(member_errors))
        errors.extend(f"hero[{index}]: {error}" for error in member_data["read_errors"])
    return member_data


def _party_probe_context_henchman(member, index, errors):
    member_errors = []
    member_data = {
        "member_index": index,
        "agent_id": _party_probe_context_int(
            _party_probe_read_attr(member, "agent_id", member_errors, None),
            "agent_id",
            member_errors,
        ),
        "h0004": _party_probe_context_int_list(
            _party_probe_read_attr(member, "h0004", member_errors, None),
            "h0004",
            member_errors,
        ),
        "profession": _party_probe_context_int(
            _party_probe_read_attr(member, "profession", member_errors, None),
            "profession",
            member_errors,
        ),
        "level": _party_probe_context_int(
            _party_probe_read_attr(member, "level", member_errors, None),
            "level",
            member_errors,
        ),
    }
    if member_errors:
        member_data["read_errors"] = sorted(set(member_errors))
        errors.extend(f"henchman[{index}]: {error}" for error in member_data["read_errors"])
    return member_data


def _party_probe_context_entry(entry, index, direction, errors):
    entry_errors = []
    players = _party_probe_read_attr(entry, "players", entry_errors, None)
    heroes = _party_probe_read_attr(entry, "heroes", entry_errors, None)
    henchmen = _party_probe_read_attr(entry, "henchmen", entry_errors, None)
    others = _party_probe_read_attr(entry, "others", entry_errors, None)

    try:
        players = list(players or [])
    except Exception as error:
        entry_errors.append(f"players: {_party_probe_error_text(error)}")
        players = []
    try:
        heroes = list(heroes or [])
    except Exception as error:
        entry_errors.append(f"heroes: {_party_probe_error_text(error)}")
        heroes = []
    try:
        henchmen = list(henchmen or [])
    except Exception as error:
        entry_errors.append(f"henchmen: {_party_probe_error_text(error)}")
        henchmen = []
    try:
        others = list(others or [])
    except Exception as error:
        entry_errors.append(f"others: {_party_probe_error_text(error)}")
        others = []

    other_ids = []
    for other_index, other in enumerate(others):
        try:
            other_ids.append(int(other))
        except Exception as error:
            entry_errors.append(f"other[{other_index}]: {_party_probe_error_text(error)}")

    entry_data = {
        "entry_index": index,
        "request_index": index if direction == "request" else None,
        "direction": direction,
        "party_id": _party_probe_context_int(
            _party_probe_read_attr(entry, "party_id", entry_errors, None),
            "party_id",
            entry_errors,
        ),
        "player_count": len(players),
        "hero_count": len(heroes),
        "henchman_count": len(henchmen),
        "other_count": len(other_ids),
        "member_count": len(players) + len(heroes) + len(henchmen) + len(other_ids),
        "players": [
            _party_probe_context_player(member, member_index, entry_errors)
            for member_index, member in enumerate(players)
        ],
        "heroes": [
            _party_probe_context_hero(member, member_index, entry_errors)
            for member_index, member in enumerate(heroes)
        ],
        "henchmen": [
            _party_probe_context_henchman(member, member_index, entry_errors)
            for member_index, member in enumerate(henchmen)
        ],
        "others": other_ids,
        "h0044": _party_probe_context_int_list(
            _party_probe_read_attr(entry, "h0044", entry_errors, None),
            "h0044",
            entry_errors,
        ),
        "invite_link": _party_probe_context_link(
            _party_probe_read_attr(entry, "invite_link", entry_errors, None),
            entry_errors,
        ),
    }
    if entry_errors:
        entry_data["read_errors"] = sorted(set(entry_errors))
        errors.extend(
            f"{direction}[{index}]: {error}" for error in entry_data["read_errors"]
        )
    return entry_data


def _party_probe_context_collection(context, collection_name, count_name, direction, errors):
    reported_count = _party_probe_context_int(
        _party_probe_read_attr(context, count_name, errors, None),
        count_name,
        errors,
    )
    raw_entries = _party_probe_read_attr(context, collection_name, errors, None)
    try:
        entries = list(raw_entries or [])
    except Exception as error:
        errors.append(f"{collection_name}: {_party_probe_error_text(error)}")
        entries = []

    entry_data = []
    for index, entry in enumerate(entries):
        try:
            entry_data.append(_party_probe_context_entry(entry, index, direction, errors))
        except Exception as error:
            entry_error = f"{direction}[{index}] parse: {_party_probe_error_text(error)}"
            errors.append(entry_error)
            entry_data.append(
                {
                    "entry_index": index,
                    "request_index": index if direction == "request" else None,
                    "direction": direction,
                    "read_errors": [entry_error],
                }
            )
    if reported_count is not None and reported_count != len(entry_data):
        errors.append(
            f"{count_name} mismatch: reported={reported_count} observed={len(entry_data)}"
        )
    return {
        "reported_count": reported_count,
        "observed_count": len(entry_data),
        "entries": entry_data,
    }


def _party_probe_capture_party_context():
    """Capture read-only native request/sending lists and preserve parse errors."""
    errors = []
    try:
        context = GWContext.Party.GetContext()
    except Exception as error:
        return {
            "available": False,
            "requests_count": None,
            "sending_count": None,
            "requests": [],
            "sending": [],
            "read_errors": [f"GWContext.Party.GetContext: {_party_probe_error_text(error)}"],
        }

    if context is None:
        return {
            "available": False,
            "requests_count": None,
            "sending_count": None,
            "requests": [],
            "sending": [],
            "read_errors": ["GWContext.Party.GetContext returned None"],
        }

    requests = _party_probe_context_collection(context, "request", "requests_count", "request", errors)
    sending = _party_probe_context_collection(context, "sending", "sending_count", "sending", errors)
    player_party = _party_probe_read_attr(context, "player_party", errors, None)
    player_party_id = None
    if player_party is not None:
        player_party_id = _party_probe_context_int(
            _party_probe_read_attr(player_party, "party_id", errors, None),
            "player_party.party_id",
            errors,
        )
    result = {
        "available": True,
        "flag": _party_probe_context_int(
            _party_probe_read_attr(context, "flag", errors, None),
            "flag",
            errors,
        ),
        "player_party_id": player_party_id,
        "requests_count": requests["reported_count"],
        "request_observed_count": requests["observed_count"],
        "requests": requests["entries"],
        "sending_count": sending["reported_count"],
        "sending_observed_count": sending["observed_count"],
        "sending": sending["entries"],
    }
    if errors:
        result["read_errors"] = sorted(set(errors))
    return result


def _party_probe_log_context_snapshot():
    """Log one manual Stage 1 snapshot; this function performs no party action."""
    global party_context_snapshot_id
    party_context_snapshot_id += 1
    state = _party_probe_capture_state()
    context = _party_probe_capture_party_context()
    _party_probe_log_context(
        "stage1_context_snapshot",
        snapshot_id=party_context_snapshot_id,
        tick=state.get("tick") if state else _party_probe_tick(),
        local_party_id=state.get("party_id") if state else None,
        local_party_size=state.get("party_size") if state else None,
        local_party_position=state.get("party_position") if state else None,
        local_is_party_leader=state.get("is_party_leader") if state else None,
        local_party_state=state,
        requests_count=context.get("requests_count"),
        sending_count=context.get("sending_count"),
        requests=context.get("requests", []),
        sending=context.get("sending", []),
        party_context=context,
    )


def _party_probe_log_context(event, **details):
    payload = {
        "probe": "PartyRequestContextProbe",
        "stage": 1,
        "read_only": True,
        "event": event,
    }
    payload.update(details)
    try:
        PySystem.Console.Log(
            PARTY_CONTEXT_LOG_MODULE,
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
        )
    except Exception:
        # A diagnostic logging failure must not affect party state.
        pass


def _party_probe_capture_state():
    """Capture B's direct local party state without shared memory or HTM paths."""
    errors = []
    tick = _party_probe_tick()

    try:
        party_instance.GetContext()
    except Exception as error:
        errors.append(f"party context: {_party_probe_error_text(error)}")

    try:
        player_instance.GetContext()
    except Exception as error:
        errors.append(f"player context: {_party_probe_error_text(error)}")

    account_email = str(_party_probe_read_attr(player_instance, "account_email", errors, "") or "")
    agent_id = _party_probe_int(_party_probe_read_attr(player_instance, "agent", errors, 0), 0)
    map_id = _party_probe_int(_party_probe_read_call(PyMap.get_map_id, "map id", errors, 0), 0)
    district = _party_probe_int(_party_probe_read_call(PyMap.get_district, "district", errors, -1), -1)
    language_id = _party_probe_int(_party_probe_read_call(PyMap.get_language, "language", errors, 255), 255)
    party_id = _party_probe_int(_party_probe_read_attr(party_instance, "party_id", errors, 0), 0)
    party_size = _party_probe_int(_party_probe_read_attr(party_instance, "party_size", errors, -1), -1)
    player_count = _party_probe_int(
        _party_probe_read_attr(party_instance, "party_player_count", errors, -1), -1
    )
    hero_count = _party_probe_int(_party_probe_read_attr(party_instance, "party_hero_count", errors, -1), -1)
    henchman_count = _party_probe_int(
        _party_probe_read_attr(party_instance, "party_henchman_count", errors, -1), -1
    )
    is_party_loaded = bool(_party_probe_read_attr(party_instance, "is_party_loaded", errors, False))
    is_party_leader = bool(_party_probe_read_attr(party_instance, "is_party_leader", errors, False))

    raw_players = _party_probe_read_attr(party_instance, "players", errors, [])
    try:
        raw_players = list(raw_players or [])
    except Exception as error:
        errors.append(f"players: {_party_probe_error_text(error)}")
        raw_players = []

    players = []
    for index, player in enumerate(raw_players):
        login_number = _party_probe_int(
            _party_probe_read_attr(player, "login_number", errors, 0), 0
        )
        member_agent_id = _party_probe_int(
            _party_probe_read_call(
                lambda login=login_number: party_instance.GetAgentIDByLoginNumber(login),
                f"player {index + 1} agent id",
                errors,
                0,
            ),
            0,
        )
        player_name = str(
            _party_probe_read_call(
                lambda login=login_number: party_instance.GetPlayerNameByLoginNumber(login),
                f"player {index + 1} name",
                errors,
                "",
            )
            or ""
        )
        players.append(
            {
                "party_position": index,
                "login_number": login_number,
                "agent_id": member_agent_id,
                "name": player_name,
                "is_connected": bool(_party_probe_read_attr(player, "is_connected", errors, False)),
                "is_ticked": bool(_party_probe_read_attr(player, "is_ticked", errors, False)),
            }
        )

    own_party_position = -1
    character_name = ""
    for player in players:
        if agent_id > 0 and player["agent_id"] == agent_id:
            own_party_position = player["party_position"]
            character_name = player["name"]
            break

    leader_id = players[0]["agent_id"] if players else 0
    other_members = _party_probe_read_attr(party_instance, "others", errors, [])
    try:
        other_count = len(other_members or [])
    except Exception as error:
        errors.append(f"other members: {_party_probe_error_text(error)}")
        other_count = -1

    snapshot = {
        "tick": tick,
        "account_email": account_email,
        "character": character_name,
        "agent_id": agent_id,
        "map_id": map_id,
        "district": district,
        "language_id": language_id,
        "party_id": party_id,
        "party_size": party_size,
        "player_count": player_count,
        "hero_count": hero_count,
        "henchman_count": henchman_count,
        "other_count": other_count,
        "party_position": own_party_position,
        "leader_id": leader_id,
        "is_party_leader": is_party_leader,
        "is_party_loaded": is_party_loaded,
        "players": players,
    }
    snapshot["is_solo"] = bool(
        party_id > 0
        and is_party_loaded
        and is_party_leader
        and party_size == 1
        and player_count == 1
        and own_party_position == 0
        and hero_count == 0
        and henchman_count == 0
        and other_count == 0
        and len(players) == 1
    )
    if errors:
        snapshot["read_errors"] = sorted(set(errors))
    return snapshot


def _party_probe_state_for_log(state):
    if state is None:
        return None
    return state


def _party_probe_signature(state):
    if state is None:
        return None
    return (
        state["map_id"],
        state["district"],
        state["language_id"],
        state["party_id"],
        state["party_size"],
        state["player_count"],
        state["hero_count"],
        state["henchman_count"],
        state["other_count"],
        state["party_position"],
        state["leader_id"],
        state["is_party_leader"],
        tuple(
            (
                player["party_position"],
                player["login_number"],
                player["agent_id"],
                player["name"],
                player["is_connected"],
                player["is_ticked"],
            )
            for player in state["players"]
        ),
    )


def _party_probe_expected_join(state):
    if state is None:
        return False
    expected_party_id = party_probe_state["expected_a_party_id"]
    if expected_party_id is None:
        return False
    return bool(
        state["party_id"] == expected_party_id
        and state["party_size"] == 2
        and state["player_count"] == 2
        and state["party_position"] > 0
        and state["leader_id"] > 0
        and state["leader_id"] != state["agent_id"]
        and state["is_party_leader"] is False
        and state["hero_count"] == 0
        and state["henchman_count"] == 0
        and state["other_count"] == 0
        and len(state["players"]) == 2
    )


def _party_probe_elapsed_ms(tick, origin):
    if tick is None or origin is None:
        return None
    return max(0, int(tick) - int(origin))


def _party_probe_timing_summary():
    return {
        "armed_tick": party_probe_state["armed_tick"],
        "invoke_tick": party_probe_state["invoke_tick"],
        "return_tick": party_probe_state["return_tick"],
        "deadline_tick": party_probe_state["deadline_tick"],
        "armed_to_invoke_ms": _party_probe_elapsed_ms(
            party_probe_state["invoke_tick"], party_probe_state["armed_tick"]
        ),
        "native_call_ms": _party_probe_elapsed_ms(
            party_probe_state["return_tick"], party_probe_state["invoke_tick"]
        ),
        "first_change_tick": party_probe_state["first_change_tick"],
        "first_change_ms": _party_probe_elapsed_ms(
            party_probe_state["first_change_tick"], party_probe_state["return_tick"]
        ),
        "last_change_tick": party_probe_state["last_change_tick"],
        "last_change_ms": _party_probe_elapsed_ms(
            party_probe_state["last_change_tick"], party_probe_state["return_tick"]
        ),
        "first_expected_tick": party_probe_state["first_expected_tick"],
        "first_expected_ms": _party_probe_elapsed_ms(
            party_probe_state["first_expected_tick"], party_probe_state["return_tick"]
        ),
        "poll_samples": party_probe_state["poll_samples"],
        "timeout_ms": PARTY_PROBE_TIMEOUT_MS,
    }


def _party_probe_failure_reason(state):
    if state is None:
        return "final_state_unavailable"
    if party_probe_state["first_change_tick"] is None:
        return "no_party_state_change"
    if state["party_id"] != party_probe_state["expected_a_party_id"]:
        return "unexpected_party_id"
    if state["is_party_leader"]:
        return "b_remained_party_leader"
    if state["party_position"] <= 0:
        return "unexpected_party_position"
    if state["player_count"] != 2 or len(state["players"]) != 2:
        return "unexpected_party_membership"
    return "incomplete_party_transition"


def _party_probe_finish(state, status, reason):
    global party_probe_direct_native_proven
    party_probe_state["status"] = status
    party_probe_state["failure_reason"] = reason
    party_probe_state["final_state"] = state
    if (
        party_probe_state["mode"] == "Direct Native"
        and status == PARTY_PROBE_SUCCEEDED
        and party_probe_state["native_return_value"] is True
        and reason == "state_match"
    ):
        party_probe_direct_native_proven = True
    summary = {
        "mode": party_probe_state["mode"],
        "expected_a_party_id": party_probe_state["expected_a_party_id"],
        "baseline_b_party_id": (
            party_probe_state["baseline"]["party_id"] if party_probe_state["baseline"] else None
        ),
        "native_return_type": party_probe_state["native_return_type"],
        "native_return_value": party_probe_state["native_return_value"],
        "native_exception": party_probe_state["native_exception"],
        "reason": reason,
        "timing": _party_probe_timing_summary(),
        "final_state": _party_probe_state_for_log(state),
    }
    event = "success_summary"
    if status == PARTY_PROBE_TIMED_OUT:
        event = "timeout_summary"
    elif status == PARTY_PROBE_FAILED:
        event = "failure_summary"
    _party_probe_log(event, **summary)


def _party_probe_start(mode):
    global party_probe_state
    global party_probe_direct_native_proven
    if party_probe_state["status"] == PARTY_PROBE_RUNNING:
        _party_probe_log("start_ignored", mode=mode, reason="probe_already_running")
        return
    if mode == "Queued Accept" and not party_probe_direct_native_proven:
        _party_probe_log("start_ignored", mode=mode, reason="direct_native_success_required")
        return
    if mode == "Direct Native":
        party_probe_direct_native_proven = False

    run_id = int(party_probe_state["run_id"]) + 1
    party_probe_state = _party_probe_new_state(run_id)
    party_probe_state["mode"] = mode
    expected_a_party_id = _party_probe_int(a_party_id_input, 0)
    party_probe_state["expected_a_party_id"] = expected_a_party_id

    baseline = _party_probe_capture_state()
    party_probe_state["baseline"] = baseline
    party_probe_state["last_state"] = baseline
    party_probe_state["last_signature"] = _party_probe_signature(baseline)
    party_probe_state["armed_tick"] = baseline["tick"]
    _party_probe_log(
        "baseline",
        mode=mode,
        expected_a_party_id=expected_a_party_id,
        state=_party_probe_state_for_log(baseline),
    )

    if expected_a_party_id <= 0:
        _party_probe_finish(baseline, PARTY_PROBE_FAILED, "invalid_a_party_id")
        return
    if not baseline["is_solo"]:
        _party_probe_finish(baseline, PARTY_PROBE_FAILED, "b_not_completely_solo")
        return
    if baseline["party_id"] == expected_a_party_id:
        _party_probe_finish(baseline, PARTY_PROBE_FAILED, "a_party_id_matches_b_party_id")
        return

    party_probe_state["status"] = PARTY_PROBE_RUNNING
    invoke_tick = _party_probe_tick()
    party_probe_state["invoke_tick"] = invoke_tick
    try:
        if mode == "Direct Native":
            result = party_instance.RespondToPartyRequest(expected_a_party_id, True)
        else:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            result = GLOBAL_CACHE.Party.RespondToPartyRequest(expected_a_party_id, True)
        party_probe_state["native_return_type"] = type(result).__name__
        party_probe_state["native_return_value"] = result
    except Exception as error:
        party_probe_state["native_exception"] = _party_probe_error_text(error)
        return_tick = _party_probe_tick()
        party_probe_state["return_tick"] = return_tick
        _party_probe_log(
            "accept_exception",
            mode=mode,
            invoke_tick=invoke_tick,
            return_tick=return_tick,
            exception=party_probe_state["native_exception"],
        )
        _party_probe_finish(baseline, PARTY_PROBE_FAILED, "accept_call_exception")
        return

    return_tick = _party_probe_tick()
    party_probe_state["return_tick"] = return_tick
    party_probe_state["deadline_tick"] = return_tick + PARTY_PROBE_TIMEOUT_MS
    _party_probe_log(
        "accept_invoked",
        mode=mode,
        a_party_id=expected_a_party_id,
        invoke_tick=invoke_tick,
        return_tick=return_tick,
        native_call_ms=_party_probe_elapsed_ms(return_tick, invoke_tick),
        native_return_type=party_probe_state["native_return_type"],
        native_return_value=party_probe_state["native_return_value"],
        note=(
            "queued owner return is not acceptance evidence"
            if mode == "Queued Accept"
            else "party-state transition remains the acceptance evidence"
        ),
    )
    if party_probe_state["native_return_value"] is False:
        _party_probe_log("native_return_false", mode=mode, a_party_id=expected_a_party_id)


def _party_probe_poll():
    if party_probe_state["status"] != PARTY_PROBE_RUNNING:
        return

    state = _party_probe_capture_state()
    tick = state["tick"]
    party_probe_state["poll_samples"] += 1
    signature = _party_probe_signature(state)
    if signature != party_probe_state["last_signature"]:
        first_change = party_probe_state["first_change_tick"] is None
        if first_change:
            party_probe_state["first_change_tick"] = tick
        party_probe_state["last_change_tick"] = tick
        party_probe_state["last_signature"] = signature
        _party_probe_log(
            "first_state_change" if first_change else "state_changed",
            mode=party_probe_state["mode"],
            tick=tick,
            elapsed_ms=_party_probe_elapsed_ms(tick, party_probe_state["return_tick"]),
            state=_party_probe_state_for_log(state),
        )

    party_probe_state["last_state"] = state
    if _party_probe_expected_join(state) and party_probe_state["first_expected_tick"] is None:
        party_probe_state["first_expected_tick"] = tick
        _party_probe_log(
            "expected_join_observed",
            mode=party_probe_state["mode"],
            tick=tick,
            elapsed_ms=_party_probe_elapsed_ms(tick, party_probe_state["return_tick"]),
            state=_party_probe_state_for_log(state),
        )

    if tick < party_probe_state["deadline_tick"]:
        return

    if _party_probe_expected_join(state):
        reason = "state_match"
        if party_probe_state["native_return_value"] is False:
            reason = "state_match_native_return_false"
        _party_probe_finish(state, PARTY_PROBE_SUCCEEDED, reason)
    else:
        _party_probe_finish(state, PARTY_PROBE_TIMED_OUT, _party_probe_failure_reason(state))


def _party_probe_reset():
    global party_probe_state
    previous_run = party_probe_state["run_id"]
    party_probe_state = _party_probe_new_state(int(previous_run) + 1)
    _party_probe_log("reset", previous_run=previous_run)


def _party_probe_draw_controls():
    global a_party_id_input
    if not PyImGui.collapsing_header("Party Request Probe (temporary)", PyImGui.TreeNodeFlags.DefaultOpen):
        return

    PyImGui.text("Stage 1: run the read-only context snapshot on A and B while the invite is pending.")
    if PyImGui.button("Log Pending Party Requests"):
        _party_probe_log_context_snapshot()
    if party_context_snapshot_id > 0:
        PyImGui.text(f"Last Stage 1 snapshot: {party_context_snapshot_id}")
    PyImGui.text("Stage 1 sends no invite, response, rejection, queue action, or retry.")
    PyImGui.text("Do not use the acceptance controls below during Stage 1.")
    PyImGui.separator()
    PyImGui.text("Stage 2 acceptance probe: run on B only after Stage 1 evidence is collected.")
    a_party_id_input = PyImGui.input_int("A Party ID (pre-invite)", a_party_id_input)
    status = party_probe_state["status"]
    mode = party_probe_state["mode"] or "-"
    PyImGui.text(f"Probe status: {status} | mode: {mode}")

    if status == PARTY_PROBE_RUNNING:
        elapsed = _party_probe_elapsed_ms(_party_probe_tick(), party_probe_state["return_tick"])
        PyImGui.text(f"Polling local party state: {elapsed} ms / {PARTY_PROBE_TIMEOUT_MS} ms")
        PyImGui.text("No automatic retry. Reset before another clean run.")
    else:
        if PyImGui.button("Direct Native Accept (Stage 2 only)"):
            _party_probe_start("Direct Native")
        if PyImGui.button("Queued Accept (Stage 2 only)"):
            _party_probe_start("Queued Accept")
        if not party_probe_direct_native_proven:
            PyImGui.text("Queued Accept is locked until Direct Native succeeds.")

    if PyImGui.button("Reset Party Request Probe"):
        _party_probe_reset()

    baseline = party_probe_state["baseline"]
    latest = party_probe_state["last_state"]
    if baseline is not None:
        PyImGui.text(
            f"Expected A party={party_probe_state['expected_a_party_id']} | "
            f"Baseline B party={baseline['party_id']}"
        )
    if latest is not None:
        PyImGui.text(
            f"Latest B state: party={latest['party_id']} pos={latest['party_position']} "
            f"leader_id={latest['leader_id']} is_leader={latest['is_party_leader']} "
            f"players={latest['player_count']}"
        )
    if party_probe_state["final_state"] is not None:
        PyImGui.text(
            f"Final result: {party_probe_state['status']} "
            f"({party_probe_state['failure_reason'] or 'state_match'})"
        )
    PyImGui.separator()

def draw_window():
    global module_name
    global party_instance
    global hero_id_input, henchman_id_input, player_id_input, x_pos_input, y_pos_input, hard_mode_flag

    try:
        party_instance.GetContext()  # Get the party context
    except Exception:
        pass
    _party_probe_poll()
    
    if PyImGui.begin(module_name):
        # Check if party is ticked
        PyImGui.text(f"Is All Party Ticked? {'Yes' if party_instance.tick.IsTicked() else 'No'}")
        if PyImGui.button("Toggle Party Tick"):
            party_instance.tick.ToggleTicked()
        if PyImGui.button("Set Tick Is a Toggle?"):
            party_instance.tick.SetTickToggle(True)
        PyImGui.separator()
        
        if PyImGui.collapsing_header("Party Info", PyImGui.TreeNodeFlags.DefaultOpen):

            _party_probe_draw_controls()
            
            # Party ID
            PyImGui.text(f"Party ID: {party_instance.party_id}")
            PyImGui.text(f"Party Size: {party_instance.party_size}")
            PyImGui.text(f"Player Count: {party_instance.party_player_count}")
            PyImGui.text(f"Hero Count: {party_instance.party_hero_count}")
            PyImGui.text(f"Henchman Count: {party_instance.party_henchman_count}")
            
            PyImGui.text(f"Is Party Defeated?: {'Yes' if party_instance.is_party_defeated else 'No'}")
            PyImGui.text(f"Is Party Loaded?: {'Yes' if party_instance.is_party_loaded else 'No'}")
            PyImGui.text(f"Is Party Leader?: {'Yes' if party_instance.is_party_leader else 'No'}")
            
            PyImGui.text(f"Is In Hard Mode: {'Yes' if party_instance.is_in_hard_mode else 'No'}")
            PyImGui.text(f"Is Hard Mode Unlocked?: {'Yes' if party_instance.is_hard_mode_unlocked else 'No'}")
            PyImGui.separator()

            # Interactive Method: Set Hard Mode
            if PyImGui.button("Set Hard Mode"):
                party_instance.SetHardMode(True)

            PyImGui.separator()

            # Players in the party
            if PyImGui.collapsing_header("Players"):

                # Interactive Method: Kick Player
                player_id_input = PyImGui.input_int("Player ID to Kick", player_id_input)

                if PyImGui.button("Invite Player"):
                    party_instance.InvitePlayer(player_id_input)

                if PyImGui.button("Kick Player"):
                    party_instance.KickPlayer(player_id_input)
                PyImGui.separator()
                
                for player in party_instance.players:
                    PyImGui.text(f"Player ID: {player.player_id}")
                    agent_id = party_instance.GetAgentByPlayerID(player.player_id)
                    PyImGui.text(f"Agent ID: {agent_id}")
                    PyImGui.text(f"Called Target ID: {player.called_target_id}")
                    PyImGui.text(f"Is Connected? {'Yes' if player.is_connected else 'No'}")
                    PyImGui.text(f"Is Ticked? {'Yes' if player.is_ticked else 'No'}")
                    PyImGui.separator()

            # Heroes in the party
            if PyImGui.collapsing_header("Heroes"):

                # Interactive Method: Add Hero
                hero_id_input = PyImGui.input_int("Hero ID to Add", hero_id_input)

                if PyImGui.button("Add Hero"):
                    party_instance.AddHero(hero_id_input)

                if PyImGui.button("Kick Hero"):
                    party_instance.KickHero(hero_id_input)

                if PyImGui.button("Kick All Heroes"):
                    party_instance.KickAllHeroes()

                PyImGui.separator()

                # Interactive Method: Flag Hero
                x_pos_input = PyImGui.input_float("Hero X Position", x_pos_input)
                y_pos_input = PyImGui.input_float("Hero Y Position", y_pos_input)

                if PyImGui.button("Flag Hero"):
                    party_instance.FlagHero(hero_id_input, x_pos_input, y_pos_input)

                if PyImGui.button("Set Hero Behavior Fight"):
                    party_instance.SetHeroBehavior(hero_id_input, 0)

                if PyImGui.button("Set Hero Behavior Guard"):
                    party_instance.SetHeroBehavior(hero_id_input, 1)

                if PyImGui.button("Set Hero Behavior Avoid"):
                    party_instance.SetHeroBehavior(hero_id_input, )

                if PyImGui.button("Cast Hero Skill"):
                    target_agent_id =27
                    skill_number = 2
                    hero_number = 1
                    party_instance.HeroUseSkill(target_agent_id, skill_number, hero_number)

                PyImGui.separator()
                
                for hero in party_instance.heroes:
                    PyImGui.text(f"Agent ID: {hero.agent_id}")
                    PyImGui.text(f"Owner Player ID: {hero.owner_player_id}")
                    PyImGui.text(f"Hero ID: {hero.hero_id.GetId()}")
                    PyImGui.text(f"Hero Name: {hero.hero_id.GetName()}")
                    PyImGui.text(f"Hero Primary: {hero.primary.GetName()}")
                    PyImGui.text(f"Hero Secondary: {hero.secondary.GetName()}")
                    PyImGui.text(f"Level: {hero.level}")
                    PyImGui.separator()
                    
                PyImGui.separator()

            # Henchmen in the party
            if PyImGui.collapsing_header("Henchmen"):

                # Interactive Method: Add Henchman
                henchman_id_input = PyImGui.input_int("Henchman ID", henchman_id_input)

                if PyImGui.button("Add Henchman"):
                    party_instance.AddHenchman(henchman_id_input)
                PyImGui.separator()

                if PyImGui.button("Kick Henchman"):
                    party_instance.KickHenchman(henchman_id_input)
                PyImGui.separator()
                
                for henchman in party_instance.henchmen:
                    PyImGui.text(f"Agent ID: {henchman.agent_id}")
                    PyImGui.text(f"Profession: {henchman.profession.GetName()}")
                    PyImGui.text(f"Level: {henchman.level}")
                    PyImGui.separator()

        PyImGui.end()


# main() must exist in every script and is the entry point for your script's execution.
def main():
    try:
        draw_window()

    # Handle specific exceptions to provide detailed error messages
    except ImportError as e:
        PySystem.Console.Log(module_name, f"ImportError encountered: {str(e)}")
    except ValueError as e:
        PySystem.Console.Log(module_name, f"ValueError encountered: {str(e)}")
    except Exception as e:
        PySystem.Console.Log(module_name, f"Unexpected error encountered: {str(e)}")
    finally:
        pass  # Replace with your actual code

# This ensures that main() is called when the script is executed directly.
if __name__ == "__main__":
    main()
