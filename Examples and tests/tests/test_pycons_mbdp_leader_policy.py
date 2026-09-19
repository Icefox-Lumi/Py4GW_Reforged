"""Offline checks for the Pycons temporary leader-controlled self MB/DP policy.

The injected Py4GW runtime is not available to this test.  It executes the
real pure policy codec, item-authorization helper, and receiver-side revoke
matcher from Pycons.py, then checks the source-level ownership boundaries that
must remain intact.

Run: python "Examples and tests/tests/test_pycons_mbdp_leader_policy.py"
Exit code 1 on any failure.
"""

import ast
import pathlib
import re
from types import SimpleNamespace
from typing import NamedTuple


ROOT = pathlib.Path(__file__).resolve().parents[2]
PYCONS_PATH = ROOT / "Widgets" / "Automation" / "Helpers" / "Pycons.py"


def _assignment_value(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                if (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "frozenset"
                    and len(node.value.args) == 1
                ):
                    return frozenset(ast.literal_eval(node.value.args[0]))
                raise
    raise AssertionError("assignment not found: %s" % name)


def _load_policy_helpers():
    source = PYCONS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PYCONS_PATH))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required_functions = (
        "_mbdp_project_self_item_effective",
        "_mbdp_control_policy_mask",
        "_mbdp_control_encode_policy",
        "_mbdp_control_decode_policy",
        "_mbdp_control_scopes_match",
        "_mbdp_control_revoke_matches",
        "_mbdp_self_policy_allows_item",
    )
    missing = [name for name in required_functions if name not in functions]
    assert not missing, "missing Pycons helper(s): %s" % ", ".join(missing)

    class_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "_MBDPSelfPolicy"
        ),
        None,
    )
    assert class_node is not None, "missing _MBDPSelfPolicy"

    namespace = {
        "NamedTuple": NamedTuple,
        "MBDP_CONTROL_PROTOCOL_VERSION": _assignment_value(tree, "MBDP_CONTROL_PROTOCOL_VERSION"),
        "MBDP_SELF_TARGET_KEYS": _assignment_value(tree, "MBDP_SELF_TARGET_KEYS"),
        "MBDP_SELF_MORALE_KEYS": _assignment_value(tree, "MBDP_SELF_MORALE_KEYS"),
        "MBDP_SELF_LIGHT_DP_KEYS": _assignment_value(tree, "MBDP_SELF_LIGHT_DP_KEYS"),
        "MBDP_SELF_STRONG_DP_KEYS": _assignment_value(tree, "MBDP_SELF_STRONG_DP_KEYS"),
        "_normalize_sync_account_email": lambda raw_value: str(raw_value or "").strip().lower(),
    }
    module = ast.Module(
        body=[
            functions["_mbdp_project_self_item_effective"],
            class_node,
            functions["_mbdp_control_policy_mask"],
            functions["_mbdp_control_encode_policy"],
            functions["_mbdp_control_decode_policy"],
            functions["_mbdp_control_scopes_match"],
            functions["_mbdp_control_revoke_matches"],
            functions["_mbdp_self_policy_allows_item"],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(PYCONS_PATH), "exec"), namespace)
    return namespace, source


NAMESPACE, SOURCE = _load_policy_helpers()
POLICY = NAMESPACE["_MBDPSelfPolicy"]
ENCODE = NAMESPACE["_mbdp_control_encode_policy"]
DECODE = NAMESPACE["_mbdp_control_decode_policy"]
ALLOWS_ITEM = NAMESPACE["_mbdp_self_policy_allows_item"]
PROJECT_SELF_ITEM = NAMESPACE["_mbdp_project_self_item_effective"]
REVOKE_MATCHES = NAMESPACE["_mbdp_control_revoke_matches"]
SELF_KEYS = tuple(NAMESPACE["MBDP_SELF_TARGET_KEYS"])


def _check(label: str, expected, observed) -> int:
    passed = expected == observed
    print("[%s] %s" % ("PASS" if passed else "FAIL", label))
    if not passed:
        print("      expected: %r" % (expected,))
        print("      observed: %r" % (observed,))
    return 0 if passed else 1


def _lease(scope: dict, *, sender: str = "leader@example", session: str = "100-2-abc", sequence: int = 4):
    return SimpleNamespace(
        protocol_version=1,
        sender_email=sender,
        party_id=scope["party_id"],
        map_id=scope["map_id"],
        map_region=scope["map_region"],
        map_district=scope["map_district"],
        map_language=scope["map_language"],
        scope_signature=scope["scope_signature"],
        session_id=session,
        sequence=sequence,
    )


def _load_mbdp_runtime_harness():
    tree = ast.parse(SOURCE, filename=str(PYCONS_PATH))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    classes = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }
    required_functions = (
        "_mbdp_control_scopes_match",
        "_mbdp_control_parse_scope",
        "_mbdp_control_session_generation",
        "_mbdp_control_decode_policy",
        "_mbdp_control_revoke_matches",
        "_mbdp_control_clear_lease",
        "_mbdp_control_reset_sender_transport",
        "_mbdp_control_reset_transport",
        "_mbdp_control_stop_broadcast",
        "_mbdp_control_refresh_lease",
        "_mbdp_control_broadcast_tick",
        "_mbdp_control_tick",
        "_pycons_handle_mbdp_control_policy",
    )
    missing = [name for name in required_functions if name not in functions]
    assert not missing, "missing runtime helper(s): %s" % ", ".join(missing)
    assert "_MBDPSelfPolicy" in classes
    assert "_MBDPControlLease" in classes

    scope = {
        "party_id": 7,
        "map_id": 42,
        "map_region": 2,
        "map_district": 1,
        "map_language": 0,
        "scope_signature": "0123456789abcdef",
    }
    revoke_calls = []
    coordinator_email = ["leader@example"]
    now_ms = [1000]
    runtime_state = SimpleNamespace(
        mbdp_control_lease=None,
        mbdp_control_status="Using local MB/DP settings",
        mbdp_control_last_broadcast_ms=0,
        mbdp_control_last_lease_check_ms=0,
        mbdp_control_last_recipients=[],
        mbdp_control_last_scope="",
        mbdp_control_sequence=0,
        mbdp_control_session_id="",
    )
    config = SimpleNamespace(
        team_consume_opt_in=True,
        mbdp_enabled=True,
        team_broadcast=False,
        mbdp_team_control_enabled=False,
    )
    namespace = {
        "NamedTuple": NamedTuple,
        "re": re,
        "MBDP_CONTROL_PROTOCOL_VERSION": _assignment_value(tree, "MBDP_CONTROL_PROTOCOL_VERSION"),
        "MBDP_CONTROL_HEARTBEAT_MS": _assignment_value(tree, "MBDP_CONTROL_HEARTBEAT_MS"),
        "MBDP_CONTROL_LEASE_TTL_MS": _assignment_value(tree, "MBDP_CONTROL_LEASE_TTL_MS"),
        "MBDP_SELF_TARGET_KEYS": _assignment_value(tree, "MBDP_SELF_TARGET_KEYS"),
        "_normalize_sync_account_email": lambda raw_value: str(raw_value or "").strip().lower(),
        "_rt": runtime_state,
        "cfg": config,
        "Player": SimpleNamespace(GetAccountEmail=lambda: "follower@example"),
        "GLOBAL_CACHE": SimpleNamespace(
            ShMem=SimpleNamespace(GetAccountDataFromEmail=lambda _email: None),
        ),
        "_current_coordinator_email": lambda _accounts=None: coordinator_email[0],
        "_get_same_party_accounts": lambda: [],
        "_mbdp_control_scope": lambda: dict(scope),
        "_pycons_message_extra_data": lambda message: tuple(message.extra),
        "_pycons_sync_account_display_name": lambda _account: "Calista",
        "_fmt_effective": lambda value: str(value),
        "_now_ms": lambda: now_ms[0],
        "_debug": lambda *_args, **_kwargs: None,
        "_mbdp_control_send_revoke": lambda reason="": revoke_calls.append(reason) or 0,
    }
    module = ast.Module(
        body=[
            classes["_MBDPSelfPolicy"],
            classes["_MBDPControlLease"],
            functions["_mbdp_control_scopes_match"],
            functions["_mbdp_control_parse_scope"],
            functions["_mbdp_control_session_generation"],
            functions["_mbdp_control_decode_policy"],
            functions["_mbdp_control_revoke_matches"],
            functions["_mbdp_control_clear_lease"],
            functions["_mbdp_control_reset_sender_transport"],
            functions["_mbdp_control_reset_transport"],
            functions["_mbdp_control_stop_broadcast"],
            functions["_mbdp_control_refresh_lease"],
            functions["_mbdp_control_broadcast_tick"],
            functions["_mbdp_control_tick"],
            functions["_pycons_handle_mbdp_control_policy"],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(PYCONS_PATH), "exec"), namespace)
    namespace["scope"] = scope
    namespace["runtime_state"] = runtime_state
    namespace["config"] = config
    namespace["coordinator_email"] = coordinator_email
    namespace["revoke_calls"] = revoke_calls
    return namespace


def _run_active_revoke_lifecycle(policy_payload: str):
    runtime = _load_mbdp_runtime_harness()
    scope = runtime["scope"]
    state = runtime["runtime_state"]
    scope_text = ",".join(
        str(scope[field])
        for field in (
            "party_id",
            "map_id",
            "map_region",
            "map_district",
            "map_language",
            "scope_signature",
        )
    )
    active_message = SimpleNamespace(
        Params=[6, 1, 1, 1],
        extra=(scope_text, "100-2-abc", policy_payload, ""),
    )
    active_handled = runtime["_pycons_handle_mbdp_control_policy"](
        active_message,
        "leader@example",
        "follower@example",
    )
    active_lease = state.mbdp_control_lease
    active_status = state.mbdp_control_status
    local_settings = {"selected": False, "runtime_enabled": False, "saved": False}
    local_settings_before = dict(local_settings)

    state.mbdp_control_sequence = 9
    state.mbdp_control_last_broadcast_ms = 123
    state.mbdp_control_last_recipients = ["old@example"]
    state.mbdp_control_last_scope = "old-scope"
    runtime["_mbdp_control_tick"]()
    lease_after_follower_tick = state.mbdp_control_lease
    status_after_follower_tick = state.mbdp_control_status
    sender_transport_after_tick = (
        state.mbdp_control_session_id,
        state.mbdp_control_sequence,
        state.mbdp_control_last_broadcast_ms,
        list(state.mbdp_control_last_recipients),
        state.mbdp_control_last_scope,
    )

    runtime["coordinator_email"][0] = None
    revoke_message = SimpleNamespace(
        Params=[6, 1, 2, 0],
        extra=(scope_text, "100-2-abc", "", ""),
    )
    revoke_handled = runtime["_pycons_handle_mbdp_control_policy"](
        revoke_message,
        "leader@example",
        "follower@example",
    )
    return {
        "active_handled": bool(active_handled),
        "active_lease": active_lease,
        "active_status": active_status,
        "lease_after_follower_tick": lease_after_follower_tick,
        "status_after_follower_tick": status_after_follower_tick,
        "sender_transport_after_tick": sender_transport_after_tick,
        "revoke_calls": list(runtime["revoke_calls"]),
        "revoke_handled": bool(revoke_handled),
        "lease_after_revoke": state.mbdp_control_lease,
        "status_after_revoke": state.mbdp_control_status,
        "local_settings_before": local_settings_before,
        "local_settings_after": local_settings,
    }


def _run_successor_revoke_lifecycle(policy_payload: str):
    runtime = _load_mbdp_runtime_harness()
    scope = runtime["scope"]
    state = runtime["runtime_state"]
    runtime["coordinator_email"][0] = "leader@example"
    scope_text = ",".join(
        str(scope[field])
        for field in (
            "party_id",
            "map_id",
            "map_region",
            "map_district",
            "map_language",
            "scope_signature",
        )
    )
    active_a = SimpleNamespace(
        Params=[6, 1, 1, 1],
        extra=(scope_text, "100-2-abc", policy_payload, ""),
    )
    handled_a = runtime["_pycons_handle_mbdp_control_policy"](
        active_a,
        "leader@example",
        "follower@example",
    )

    runtime["coordinator_email"][0] = "successor@example"
    active_b = SimpleNamespace(
        Params=[6, 1, 1, 1],
        extra=(scope_text, "200-3-def", policy_payload, ""),
    )
    handled_b = runtime["_pycons_handle_mbdp_control_policy"](
        active_b,
        "successor@example",
        "follower@example",
    )
    successor_lease = state.mbdp_control_lease

    old_a_revoke = SimpleNamespace(
        Params=[6, 1, 2, 0],
        extra=(scope_text, "100-2-abc", "", ""),
    )
    old_a_revoke_handled = runtime["_pycons_handle_mbdp_control_policy"](
        old_a_revoke,
        "leader@example",
        "follower@example",
    )
    return {
        "handled_a": bool(handled_a),
        "handled_b": bool(handled_b),
        "successor_lease": successor_lease,
        "old_a_revoke_handled": bool(old_a_revoke_handled),
        "lease_after_old_a_revoke": state.mbdp_control_lease,
    }


def main() -> int:
    failures = 0
    pumpkin = "pumpkin_cookie"
    clover = "four_leaf_clover"
    assert pumpkin in SELF_KEYS
    assert clover not in SELF_KEYS

    leader_policy = POLICY(
        target_effective=10,
        min_morale_gain=4,
        prefer_seal=False,
        allowed_items=frozenset((pumpkin, "refined_jelly")),
        respect_follower_item_enablement=True,
        source_email="leader@example",
    )
    encoded = ENCODE(leader_policy)
    decoded = DECODE(encoded, source_email="leader@example")
    failures += _check("policy codec round-trips self-planner fields", leader_policy, decoded)
    failures += _check(
        "invalid policy payload is rejected",
        None,
        DECODE("10,4,0,1,999999", source_email="leader@example"),
    )
    pumpkin_projected = PROJECT_SELF_ITEM(pumpkin, -15)
    failures += _check(
        "Pumpkin projects +10 self morale from -15 DP",
        -5,
        pumpkin_projected,
    )
    failures += _check(
        "Pumpkin projection remains below the leader's +10 target",
        True,
        pumpkin_projected < leader_policy.target_effective,
    )

    failures += _check(
        "leader-approved item with follower item enabled is usable",
        True,
        ALLOWS_ITEM(pumpkin, leader_policy.allowed_items, True, True, True),
    )
    failures += _check(
        "respect ON blocks a locally disabled follower item",
        False,
        ALLOWS_ITEM(pumpkin, leader_policy.allowed_items, True, False, False),
    )
    failures += _check(
        "respect OFF permits a leader-approved physically available item",
        True,
        ALLOWS_ITEM(pumpkin, leader_policy.allowed_items, False, False, False),
    )
    failures += _check(
        "leader disallow still blocks a locally enabled item",
        False,
        ALLOWS_ITEM("seal_of_the_dragon_empire", leader_policy.allowed_items, False, True, True),
    )
    local_state = {"selected": False, "runtime_enabled": False}
    local_state_before = dict(local_state)
    ALLOWS_ITEM(
        pumpkin,
        leader_policy.allowed_items,
        False,
        local_state["selected"],
        local_state["runtime_enabled"],
    )
    failures += _check(
        "leader authorization does not mutate follower item state",
        local_state_before,
        local_state,
    )

    scope = {
        "party_id": 7,
        "map_id": 42,
        "map_region": 2,
        "map_district": 1,
        "map_language": 0,
        "scope_signature": "0123456789abcdef",
    }
    active_lease = _lease(scope)
    failures += _check(
        "valid lease-owner revoke immediately matches the active lease",
        (True, "accepted"),
        REVOKE_MATCHES(active_lease, "leader@example", scope, scope, 1, 5, "100-2-abc"),
    )
    failures += _check(
        "wrong sender cannot revoke the active lease",
        False,
        REVOKE_MATCHES(active_lease, "other@example", scope, scope, 1, 5, "100-2-abc")[0],
    )
    failures += _check(
        "old session or generation cannot revoke a newer lease",
        False,
        REVOKE_MATCHES(active_lease, "leader@example", scope, scope, 1, 5, "0ff-1-old")[0],
    )
    failures += _check(
        "stale revoke sequence cannot clear the active lease",
        False,
        REVOKE_MATCHES(active_lease, "leader@example", scope, scope, 1, 4, "100-2-abc")[0],
    )
    failures += _check(
        "wrong protocol cannot revoke the active lease",
        False,
        REVOKE_MATCHES(active_lease, "leader@example", scope, scope, 2, 5, "100-2-abc")[0],
    )
    wrong_scope = dict(scope, map_id=43)
    failures += _check(
        "wrong party or map scope cannot revoke the active lease",
        False,
        REVOKE_MATCHES(active_lease, "leader@example", wrong_scope, scope, 1, 5, "100-2-abc")[0],
    )
    lease_state = {"lease": active_lease, "selected": False, "runtime_enabled": False}
    lease_state_before_revoke = dict(lease_state)
    revoke_matches, _revoke_reason = REVOKE_MATCHES(
        lease_state["lease"],
        "leader@example",
        scope,
        scope,
        1,
        5,
        "100-2-abc",
    )
    if revoke_matches:
        lease_state["lease"] = None
    failures += _check(
        "valid revoke clears only the runtime lease and not follower settings",
        {"lease": None, "selected": lease_state_before_revoke["selected"], "runtime_enabled": lease_state_before_revoke["runtime_enabled"]},
        lease_state,
    )

    lifecycle = _run_active_revoke_lifecycle(encoded)
    failures += _check(
        "production active handler creates a follower lease and status",
        True,
        lifecycle["active_handled"]
        and lifecycle["active_lease"] is not None
        and lifecycle["active_status"] == "Following leader@example's Morale/DP settings",
    )
    failures += _check(
        "production follower inactive path preserves the remote lease and status",
        True,
        lifecycle["lease_after_follower_tick"] is not None
        and lifecycle["status_after_follower_tick"] == lifecycle["active_status"],
    )
    failures += _check(
        "follower inactive path resets sender transport without sending a revoke",
        ("", 0, 0, [], ""),
        lifecycle["sender_transport_after_tick"],
    )
    failures += _check(
        "follower inactive path does not send a revoke",
        [],
        lifecycle["revoke_calls"],
    )
    failures += _check(
        "production matching revoke clears lease and status with no current coordinator",
        True,
        lifecycle["revoke_handled"]
        and lifecycle["lease_after_revoke"] is None
        and lifecycle["status_after_revoke"] == "Using local MB/DP settings",
    )
    failures += _check(
        "production active/revoke lifecycle leaves local settings unchanged",
        lifecycle["local_settings_before"],
        lifecycle["local_settings_after"],
    )

    successor = _run_successor_revoke_lifecycle(encoded)
    failures += _check(
        "production accepts active leases from coordinator A then successor B",
        True,
        successor["handled_a"]
        and successor["handled_b"]
        and successor["successor_lease"] is not None
        and successor["successor_lease"].sender_email == "successor@example",
    )
    failures += _check(
        "departed coordinator A can revoke its own lease after coordinator election changes",
        True,
        successor["old_a_revoke_handled"]
        and successor["lease_after_old_a_revoke"] is successor["successor_lease"],
    )

    failures += _check(
        "policy payload stays limited to self-planner fields",
        False,
        any(
            name in SOURCE[SOURCE.index("def _mbdp_control_encode_policy"):SOURCE.index("def _mbdp_control_decode_policy")]
            for name in (
                "mbdp_party_target_effective",
                "mbdp_party_min_members",
                "mbdp_party_min_interval_ms",
                "mbdp_party_light_dp_threshold",
            )
        ),
    )
    failures += _check(
        "no second follower opt-in setting was introduced",
        False,
        "mbdp_team_control_opt_in" in SOURCE,
    )
    failures += _check(
        "coordinator election does not require follower opt-in to be OFF",
        False,
        "team_consume_opt_in" in SOURCE[
            SOURCE.index("def _current_coordinator_email") : SOURCE.index("def _coordinator_gate")
        ],
    )
    failures += _check(
        "party-wide planner remains separate from temporary self policy",
        False,
        "_mbdp_control_effective_self_policy" in SOURCE[
            SOURCE.index("def _mbdp_prepare_party_context") : SOURCE.index("def _mbdp_select_candidate_item")
        ],
    )
    failures += _check(
        "leader option defaults OFF",
        True,
        '"mbdp_team_control_enabled": False' in SOURCE,
    )
    failures += _check(
        "follower item-respect option defaults ON",
        True,
        '"mbdp_team_control_respect_follower_item_enablement": True' in SOURCE,
    )
    handler_start = SOURCE.index("def _pycons_handle_mbdp_control_policy")
    handler_end = SOURCE.index("def pycons_handle_shared_message", handler_start)
    handler_source = SOURCE[handler_start:handler_end]
    revoke_start = handler_source.index("if active_flag == 0")
    active_start = handler_source.index("coordinator_email = _current_coordinator_email")
    failures += _check(
        "lease receiver does not mutate follower config or runtime item state",
        False,
        any(
            marker in handler_source
            for marker in (
                "cfg.selected[",
                "cfg.enabled[",
                "_rt.runtime_selected[",
                "_rt.runtime_enabled[",
                "cfg.save",
                "cfg.mark_dirty",
            )
        ),
    )
    failures += _check(
        "local MB/DP OFF remains a self-tick hard stop",
        True,
        "if not bool(cfg.mbdp_enabled):" in SOURCE[
            SOURCE.index("def _mbdp_tick_precheck") : SOURCE.index("def _mbdp_run_self_phase")
        ],
    )
    failures += _check(
        "explicit remote item calls retain their receiver-owned gate",
        True,
        "mbdp_receiver_require_enabled" in SOURCE[
            SOURCE.index("def pycons_should_consume_broadcast_item") : SOURCE.index("def _is_conset_key")
        ],
    )
    broadcast_source = SOURCE[
        SOURCE.index("def _mbdp_control_broadcast_tick") : SOURCE.index("def _mbdp_control_tick")
    ]
    failures += _check(
        "leader control requires the explicit leader switch",
        True,
        '"mbdp_team_control_enabled"' in broadcast_source,
    )
    failures += _check(
        "leader control stops when local MB/DP is OFF",
        True,
        '"mbdp_enabled"' in broadcast_source,
    )
    failures += _check(
        "follower opt-out clears the temporary lease",
        True,
        '"follower team opt-in is OFF"' in handler_source,
    )
    failures += _check(
        "wrong coordinator is rejected",
        True,
        "current coordinator is" in handler_source,
    )
    failures += _check(
        "active policy frames retain current-coordinator validation",
        True,
        "current coordinator is" in handler_source[active_start:],
    )
    failures += _check(
        "revoke validation uses lease ownership instead of current coordinator",
        True,
        "_current_coordinator_email" not in handler_source[revoke_start:active_start],
    )
    failures += _check(
        "wrong party or map scope is rejected",
        True,
        "scope does not match this client" in handler_source,
    )
    failures += _check(
        "stale and out-of-order leases are rejected",
        True,
        "stale session" in handler_source and "out-of-order" in handler_source,
    )
    failures += _check(
        "lease expiry and reload reset are implemented",
        True,
        "lease heartbeat expired" in SOURCE and "Pycons config reloaded" in SOURCE,
    )
    failures += _check(
        "reload and account rebind explicitly retain local lease reset behavior",
        True,
        '"account configuration rebound", clear_local_lease=True' in SOURCE
        and '"Pycons config reloaded", clear_local_lease=True' in SOURCE,
    )
    stop_start = SOURCE.index("def _mbdp_control_stop_broadcast")
    stop_end = SOURCE.index("def _mbdp_control_refresh_lease", stop_start)
    stop_source = SOURCE[stop_start:stop_end]
    failures += _check(
        "leader stop sends an explicit revoke before sender transport reset",
        True,
        "_mbdp_control_send_revoke(reason)" in stop_source
        and stop_source.index("_mbdp_control_send_revoke(reason)")
        < stop_source.index("_mbdp_control_reset_sender_transport()"),
    )
    reset_start = SOURCE.index("def _mbdp_control_reset_transport")
    reset_end = SOURCE.index("def _mbdp_control_send_revoke", reset_start)
    reset_source = SOURCE[reset_start:reset_end]
    failures += _check(
        "ordinary sender teardown does not clear receiver leases",
        True,
        "_mbdp_control_clear_lease" not in stop_source
        and "_mbdp_control_clear_lease(reason)" in reset_source,
    )
    failures += _check(
        "revoke frame uses the existing Pycons policy opcode and inactive flag",
        True,
        "SharedCommandType.Pycons" in SOURCE[SOURCE.index("def _mbdp_control_send_revoke"):SOURCE.index("def _mbdp_control_stop_broadcast")] and "0.0" in SOURCE[SOURCE.index("def _mbdp_control_send_revoke"):SOURCE.index("def _mbdp_control_stop_broadcast")],
    )
    for transition, marker in (
        ("leader control OFF", '"mbdp_team_control_enabled"'),
        ("team broadcast OFF", '"team_broadcast"'),
        ("leader MB/DP OFF", '"mbdp_enabled"'),
    ):
        failures += _check(
            "%s uses immediate revoke fallback" % transition,
            True,
            marker in broadcast_source and "_mbdp_control_stop_broadcast" in broadcast_source,
        )
    failures += _check(
        "receiver validates revocation identity, scope, session, protocol, and sequence",
        True,
        all(
            marker in handler_source
            for marker in (
                "_mbdp_control_revoke_matches",
                "coordinator policy revoked",
                "active_flag == 0",
                "protocol_version != int(MBDP_CONTROL_PROTOCOL_VERSION)",
            )
        ),
    )

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
