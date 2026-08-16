from __future__ import annotations

from collections.abc import Callable
import time

import PySystem

from Py4GWCoreLib import Agent, AgentArray, GLOBAL_CACHE, Player, SharedCommandType
from Py4GWCoreLib.BottingTree import BottingTree
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.routines_src.behaviourtrees_src.shared import BTShared
from Sources.ApoSource.ApoBottingLib import wrappers as BT
from Widgets.System.Messaging import get_inventory_count, reset_inventory_count

from .NicholasFarms import (
    FLOW_CHALLENGE,
    FLOW_DIALOG,
    FLOW_DIRECT,
    FLOW_FOW,
    FLOW_PORTAL_LOOP,
    FLOW_TWO_MAP,
    FarmDefinition,
)


MODULE_NAME = "Nicholas Farm Base"

_PREPARED_KEY = "__nicholas_manager_prepared"
_PORTAL_READY_KEY = "__nicholas_manager_portal_ready"

_INVENTORY_QUERY_TIMEOUT_MS = 10_000
_INVENTORY_QUERY_POLL_MS = 100


def configure_tree(tree: BottingTree) -> BottingTree:
    """
    Common Nicholas runtime policy.

    Inventory maintenance is intentionally disabled during the farm because
    MerchantRules is also disabled on every multibox client while the native
    item/map-transition crash is being investigated.
    """
    return tree.Config.ConfigureUpkeep(
        looting_enabled=True,
        resurrection_scroll=False,
        auto_inventory_handler_enabled=False,
        restore_auto_inventory_handler_on_stop=True,
        enable_party_wipe_recovery=False,
        heroai_state_logging=False,
    )


def disable_merchant_rules_all_accounts() -> BehaviorTree:
    """
    Disable MerchantRules once on leader + all active shared-memory accounts.

    There is deliberately no BottingTree widget policy here: the command is
    dispatched once and acknowledged, so WidgetHandler is not touched on every
    tick.
    """
    return BTShared.SendAndWait(
        command=SharedCommandType.DisableWidget,
        extra_data=("MerchantRules", "", "", ""),
        include_self=True,
        refs_blackboard_key="__nicholas_disable_merchant_rules_refs",
        timeout_ms=10_000,
        poll_interval_ms=100,
        log=True,
        aftercast_ms=100,
    )


def _range_for_farm(farm: FarmDefinition) -> float:
    if farm.clear_radius == "Spirit":
        return Range.Spirit.value
    return Range.Earshot.value


def prepare_farm(tree_getter: Callable[[], BottingTree], farm: FarmDefinition) -> BehaviorTree:
    """
    One-time setup per manual Start:

      MerchantRules OFF on all accounts
      -> aggressive multibox HeroAI
      -> leave current party
      -> travel to farm outpost
      -> create multibox party
      -> Normal Mode

    The blackboard flag survives planner repeats, so the party is not rebuilt
    after each farm run.
    """
    tree = tree_getter()

    return BT.Selector(
        name="Prepare Farm",
        children=[
            BT.HasBlackboardValue(_PREPARED_KEY, log=False),
            BT.Sequence(
                name="Initial Farm Setup",
                children=[
                    disable_merchant_rules_all_accounts(),
                    tree.Config.Aggressive(
                        multi_account=True,
                        account_isolation=False,
                        auto_loot=True,
                        resurrection_scroll=False,
                        reset_hero_ai=True,
                    ),
                    BT.LeaveParty(),
                    BT.Travel(
                        target_map_id=farm.outpost_map_id,
                        random_travel=False,
                        log=True,
                    ),
                    BT.CreateParty(
                        multibox_invite=True,
                        timeout_ms=20_000,
                        log=True,
                    ),
                    BT.SetHardMode(
                        hard_mode=False,
                        log=False,
                    ),
                    BT.SaveBlackboardValue(
                        _PREPARED_KEY,
                        True,
                        log=False,
                    ),
                ],
            ),
        ],
    )


def _account_map_tuple(account: object) -> tuple[int, int, int, int]:
    map_obj = getattr(getattr(account, "AgentData", None), "Map", None)
    return (
        int(getattr(account, "MapID", 0) or getattr(map_obj, "MapID", 0) or 0),
        int(getattr(account, "MapRegion", 0) or getattr(map_obj, "Region", 0) or 0),
        int(getattr(account, "MapDistrict", 0) or getattr(map_obj, "District", 0) or 0),
        int(getattr(account, "MapLanguage", 0) or getattr(map_obj, "Language", 0) or 0),
    )


def _account_party_id(account: object) -> int:
    return int(
        getattr(
            getattr(account, "AgentPartyData", None),
            "PartyID",
            0,
        )
        or 0
    )


def _account_label(account: object) -> str:
    agent_data = getattr(account, "AgentData", None)
    character_name = str(getattr(agent_data, "CharacterName", "") or "").strip()
    if character_name:
        return character_name
    return str(getattr(account, "AccountEmail", "") or "Unknown account")


def farm_party_accounts() -> list[tuple[str, str]]:
    """
    Resolve the accounts belonging to the current farming party.

    PartyID is preferred. During the short periods where PartyID is not
    populated, the current map instance is used as a fallback.
    """
    local_email = str(Player.GetAccountEmail() or "").strip()
    if not local_email:
        return []

    try:
        local_account = GLOBAL_CACHE.ShMem.GetAccountDataFromEmail(local_email)
    except Exception:
        local_account = None

    try:
        accounts = GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False)
    except TypeError:
        accounts = GLOBAL_CACHE.ShMem.GetAllAccountData()
    except Exception:
        accounts = []

    local_party_id = _account_party_id(local_account) if local_account is not None else 0
    local_map = _account_map_tuple(local_account) if local_account is not None else None

    result: list[tuple[str, str]] = []
    seen: set[str] = set()

    for account in accounts or []:
        email = str(getattr(account, "AccountEmail", "") or "").strip()
        if not email or email in seen:
            continue

        same_party = (
            local_party_id > 0
            and _account_party_id(account) == local_party_id
        )
        same_map_fallback = (
            local_party_id <= 0
            and local_map is not None
            and _account_map_tuple(account) == local_map
        )

        if not same_party and not same_map_fallback:
            continue

        seen.add(email)
        result.append((email, _account_label(account)))

    if local_email not in seen:
        local_name = str(Player.GetName() or "").strip()
        result.append((local_email, local_name or local_email))

    return result


def check_target_item_count(
    *,
    farm: FarmDefinition,
    target_getter: Callable[[], int],
    result_callback: Callable[[int, dict[str, int], dict[str, str]], None],
    stop_callback: Callable[[], None],
) -> BehaviorTree:
    """
    Count the selected Nicholas item across the whole farming party.

    The local inventory is read directly. Followers are queried through
    SharedCommandType.InventoryQuery. The target is collective, not per-account.
    """
    state: dict[str, object] = {
        "initialized": False,
        "local_email": "",
        "targets": [],
        "index": 0,
        "waiting": False,
        "request_started_at": 0.0,
        "counts": {},
        "labels": {},
    }

    def _reset_state() -> None:
        state["initialized"] = False
        state["local_email"] = ""
        state["targets"] = []
        state["index"] = 0
        state["waiting"] = False
        state["request_started_at"] = 0.0
        state["counts"] = {}
        state["labels"] = {}

    def _finish() -> BehaviorTree.NodeState:
        counts = {
            str(email): int(count)
            for email, count in dict(state["counts"]).items()
        }
        labels = {
            str(email): str(label)
            for email, label in dict(state["labels"]).items()
        }

        total = sum(counts.values())
        target = max(1, int(target_getter()))
        result_callback(total, counts, labels)

        details = " | ".join(
            f"{labels.get(email, email)}={count}"
            for email, count in counts.items()
        )
        PySystem.Console.Log(
            MODULE_NAME,
            (
                f"{farm.name}: {total}/{target}"
                + (f" | {details}" if details else "")
            ),
            PySystem.Console.MessageType.Info,
        )

        if total >= target:
            PySystem.Console.Log(
                MODULE_NAME,
                f"Target reached for {farm.name}: {total}/{target}. Stopping.",
                PySystem.Console.MessageType.Success,
            )
            stop_callback()

        _reset_state()
        return BehaviorTree.NodeState.SUCCESS

    def _tick(_node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        local_email = str(Player.GetAccountEmail() or "").strip()
        if not local_email:
            return BehaviorTree.NodeState.RUNNING

        if not bool(state["initialized"]):
            targets = farm_party_accounts()
            if not targets:
                return BehaviorTree.NodeState.RUNNING

            state["initialized"] = True
            state["local_email"] = local_email
            state["targets"] = targets
            state["index"] = 0
            state["waiting"] = False
            state["counts"] = {}
            state["labels"] = {
                email: label
                for email, label in targets
            }

        targets = list(state["targets"])
        index = int(state["index"])

        if index >= len(targets):
            return _finish()

        email, _label = targets[index]
        email = str(email)
        model_id = int(farm.model_id)

        if email == local_email:
            try:
                count = int(GLOBAL_CACHE.Inventory.GetModelCount(model_id))
            except Exception:
                count = 0

            counts = dict(state["counts"])
            counts[email] = count
            state["counts"] = counts
            state["index"] = index + 1
            state["waiting"] = False
            return BehaviorTree.NodeState.RUNNING

        if not bool(state["waiting"]):
            reset_inventory_count(email, model_id, model_id)

            GLOBAL_CACHE.ShMem.SendMessage(
                local_email,
                email,
                SharedCommandType.InventoryQuery,
                (float(model_id), float(model_id), 0.0, 0.0),
                ("report_inventory_count",),
            )

            state["waiting"] = True
            state["request_started_at"] = time.monotonic()
            return BehaviorTree.NodeState.RUNNING

        count = int(get_inventory_count(email, model_id, model_id))

        if count >= 0:
            counts = dict(state["counts"])
            counts[email] = count
            state["counts"] = counts
            state["index"] = index + 1
            state["waiting"] = False
            state["request_started_at"] = 0.0
            return BehaviorTree.NodeState.RUNNING

        elapsed_ms = (
            time.monotonic()
            - float(state["request_started_at"])
        ) * 1000.0

        if elapsed_ms >= _INVENTORY_QUERY_TIMEOUT_MS:
            PySystem.Console.Log(
                MODULE_NAME,
                f"Inventory query timed out for {email}; retrying.",
                PySystem.Console.MessageType.Warning,
            )
            reset_inventory_count(email, model_id, model_id)
            state["waiting"] = False
            state["request_started_at"] = 0.0

        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree(
        BehaviorTree.ActionNode(
            name=f"Check {farm.name} Total",
            action_fn=_tick,
            aftercast_ms=_INVENTORY_QUERY_POLL_MS,
        )
    )


def farm_path(farm: FarmDefinition) -> BehaviorTree:
    return BT.VanquishNode(
        farm.farm_path,
        name=f"Farm {farm.name}",
        clear_area_radius=_range_for_farm(farm),
        pause_on_combat=True,
        flag_heroes_to_waypoint=False,
        move_tolerance=175.0,
        log=False,
    )


def resign_and_return(farm: FarmDefinition) -> BehaviorTree:
    """
    Reset a normal farm instance.

    The pre-resign and post-load waits are intentionally centralized here so
    every resign-based farm uses the same item/transition safety policy.
    """
    return BT.Sequence(
        name="Resign And Return",
        children=[
            BT.WaitUntilOutOfCombat(
                range=Range.Earshot.value,
                timeout_ms=60_000,
            ),
            BT.Wait(3_000),
            BT.Resign(
                wait_for_map_load=True,
                target_map_id=farm.outpost_map_id,
                multi_account=True,
                timeout_ms=60_000,
                log=True,
            ),
            BT.Wait(3_000),
        ],
    )


def prepare_portal_once(farm: FarmDefinition) -> BehaviorTree:
    return BT.Selector(
        name="Prepare Farm Portal",
        children=[
            BT.HasBlackboardValue(_PORTAL_READY_KEY, log=False),
            BT.Sequence(
                name="Initial Trip To Farm Portal",
                children=[
                    BT.MoveAndExitMap(
                        farm.exit_point,
                        target_map_id=farm.reset_map_id,
                        timeout_ms=45_000,
                        log=True,
                    ),
                    BT.VanquishNode(
                        farm.transit_path,
                        name="Initial Transit To Farm Portal",
                        clear_area_radius=Range.Earshot.value,
                        pause_on_combat=True,
                        flag_heroes_to_waypoint=False,
                        move_tolerance=175.0,
                        log=True,
                    ),
                    BT.SaveBlackboardValue(
                        _PORTAL_READY_KEY,
                        True,
                        log=False,
                    ),
                ],
            ),
        ],
    )


def reset_via_portal(farm: FarmDefinition) -> BehaviorTree:
    return BT.Sequence(
        name="Reset Farm Via Portal",
        children=[
            BT.WaitUntilOutOfCombat(
                range=Range.Earshot.value,
                timeout_ms=60_000,
            ),
            BT.Wait(3_000),
            BT.MoveAndExitMap(
                farm.portal_back,
                target_map_id=farm.reset_map_id,
                timeout_ms=60_000,
                log=True,
            ),
            BT.Wait(3_000),
        ],
    )


def wait_for_agent_model(model_id: int, timeout_ms: int = 20_000) -> BehaviorTree:
    state = {"started": 0.0}

    def _check(_node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if state["started"] <= 0.0:
            state["started"] = time.monotonic()

        try:
            for agent_id in AgentArray.GetNPCMinipetArray():
                if (
                    Agent.IsValid(agent_id)
                    and int(Agent.GetModelID(agent_id) or 0) == int(model_id)
                ):
                    return BehaviorTree.NodeState.SUCCESS
        except Exception:
            pass

        if (time.monotonic() - state["started"]) * 1000.0 >= timeout_ms:
            state["started"] = 0.0
            return BehaviorTree.NodeState.FAILURE

        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree(
        BehaviorTree.ActionNode(
            name=f"Wait For Agent Model {model_id}",
            action_fn=_check,
            aftercast_ms=250,
        )
    )


def enter_fow(farm: FarmDefinition) -> BehaviorTree:
    return BT.Sequence(
        name="Enter Fissure Of Woe",
        children=[
            BT.Move(
                farm.balthazar_approach,
                pause_on_combat=False,
                flag_heroes_to_waypoint=False,
                log=False,
            ),
            BT.SendChatCommand("kneel", log=True),
            wait_for_agent_model(farm.balthazar_champion_model_id),
            BT.TargetAgentByModelIDAndSendDialog(
                farm.balthazar_champion_model_id,
                dialog_id=0x85,
                log=True,
                multi_account=False,
            ),
            BT.Wait(500),
            BT.SendDialog(
                dialog_id=0x86,
                log=True,
                multi_account=False,
            ),
            BT.WaitForMapLoad(
                map_id=farm.farm_map_id,
                timeout_ms=45_000,
            ),
        ],
    )



def build_nicholas_exchange(farm: FarmDefinition) -> BehaviorTree:
    """
    Travel to Nicholas and exchange the selected weekly item on all accounts.

    The route is migrated from the legacy AutoIt Exchange script. Movement is
    kept data-driven in NicholasFarms.py; this function is shared by every farm.

    Collector conversions are not silently invented here. For farms whose
    requested Nicholas item is obtained from a collector, the UI tells the user
    that the collector conversion must be completed before this exchange route.
    """
    if not farm.exchange_available:
        return BT.LogMessage(
            message=f"No legacy Nicholas exchange route is available for {farm.name}.",
            module_name=MODULE_NAME,
        )

    children: list[BehaviorTree | BehaviorTree.Node] = [
        disable_merchant_rules_all_accounts(),
        BT.Travel(
            target_map_id=farm.exchange_town_map_id,
            random_travel=False,
            log=True,
        ),
        BT.SetHardMode(
            hard_mode=False,
            log=False,
        ),
    ]

    pending_kind = ""
    pending_points: list[tuple[float, float]] = []

    def flush_pending() -> None:
        nonlocal pending_kind, pending_points

        if not pending_points:
            pending_kind = ""
            return

        points = list(pending_points)

        if pending_kind == "aggro":
            children.append(
                BT.VanquishNode(
                    points,
                    name="Route To Nicholas",
                    clear_area_radius=Range.Earshot.value,
                    pause_on_combat=True,
                    flag_heroes_to_waypoint=False,
                    move_tolerance=175.0,
                    log=False,
                )
            )
        else:
            children.append(
                BT.Move(
                    points,
                    pause_on_combat=False,
                    flag_heroes_to_waypoint=False,
                    log=False,
                )
            )

        pending_kind = ""
        pending_points = []

    for kind, point, target_map_id in farm.exchange_actions:
        if kind in ("move", "aggro"):
            if pending_kind and pending_kind != kind:
                flush_pending()
            pending_kind = kind
            pending_points.append(point)
            continue

        flush_pending()

        if kind == "exit":
            children.append(
                BT.MoveAndExitMap(
                    point,
                    target_map_id=int(target_map_id),
                    timeout_ms=60_000,
                    log=True,
                )
            )
            children.append(BT.Wait(3_000))
            continue

        raise ValueError(
            f"Unsupported Nicholas exchange action '{kind}' for {farm.name}."
        )

    flush_pending()

    children.extend(
        [
            BT.WaitUntilOutOfCombat(
                range=Range.Earshot.value,
                timeout_ms=60_000,
            ),
            BT.Wait(1_500),
            BT.TargetNearestAndSendDialog(
                farm.nicholas_position,
                dialog_id=0x85,
                target_distance=Range.Nearby.value,
                log=True,
                multi_account=True,
            ),
            BT.Wait(1_000),
            BT.SendDialog(
                dialog_id=0x86,
                log=True,
                multi_account=True,
            ),
            BT.Wait(1_500),
        ]
    )

    return BT.Sequence(
        name=f"Exchange {farm.nicholas_item_name} With Nicholas",
        children=children,
    )


def build_exchange_steps(
    farm: FarmDefinition,
) -> list[tuple[str, Callable[[], BehaviorTree]]]:
    return [
        (
            "Travel And Exchange With Nicholas",
            lambda: build_nicholas_exchange(farm),
        ),
    ]

def build_execution_steps(
    *,
    tree_getter: Callable[[], BottingTree],
    farm: FarmDefinition,
    count_node_factory: Callable[[], BehaviorTree],
) -> list[tuple[str, Callable[[], BehaviorTree]]]:
    """
    Build the planner for the selected farm from its small FarmDefinition.

    This is the core of the manager architecture: 76 farms share this engine;
    only their data and structural entry/reset type differ.
    """
    steps: list[tuple[str, Callable[[], BehaviorTree]]] = [
        ("Prepare Farm", lambda: prepare_farm(tree_getter, farm)),
        ("Check Target Count", count_node_factory),
    ]

    if farm.flow == FLOW_DIRECT:
        steps.extend(
            [
                (
                    "Go Out",
                    lambda: BT.MoveAndExitMap(
                        farm.exit_point,
                        target_map_id=farm.farm_map_id,
                        timeout_ms=45_000,
                        log=False,
                    ),
                ),
                ("Farm Path", lambda: farm_path(farm)),
                ("Resign And Return", lambda: resign_and_return(farm)),
            ]
        )

    elif farm.flow == FLOW_TWO_MAP:
        steps.extend(
            [
                (
                    "Go Out",
                    lambda: BT.MoveAndExitMap(
                        farm.exit_point,
                        target_map_id=farm.transit_map_id,
                        timeout_ms=45_000,
                        log=True,
                    ),
                ),
                (
                    "Cross First Map",
                    lambda: BT.VanquishNode(
                        farm.transit_path,
                        name="Cross First Map",
                        clear_area_radius=Range.Earshot.value,
                        pause_on_combat=True,
                        flag_heroes_to_waypoint=False,
                        move_tolerance=175.0,
                        log=True,
                    ),
                ),
                (
                    "Enter Farm Map",
                    lambda: BT.MoveAndExitMap(
                        farm.portal_to_farm,
                        target_map_id=farm.farm_map_id,
                        timeout_ms=60_000,
                        log=True,
                    ),
                ),
                ("Farm Path", lambda: farm_path(farm)),
                ("Resign And Return", lambda: resign_and_return(farm)),
            ]
        )

    elif farm.flow == FLOW_PORTAL_LOOP:
        steps.extend(
            [
                ("Prepare Farm Portal", lambda: prepare_portal_once(farm)),
                (
                    "Enter Farm Map",
                    lambda: BT.MoveAndExitMap(
                        farm.portal_to_farm,
                        target_map_id=farm.farm_map_id,
                        timeout_ms=60_000,
                        log=True,
                    ),
                ),
                ("Farm Path", lambda: farm_path(farm)),
                ("Reset Via Portal", lambda: reset_via_portal(farm)),
            ]
        )

    elif farm.flow == FLOW_CHALLENGE:
        steps.extend(
            [
                (
                    "Enter Challenge",
                    lambda: BT.EnterChallenge(
                        delay_ms=farm.challenge_delay_ms,
                        target_map_id=farm.farm_map_id,
                    ),
                ),
                ("Farm Path", lambda: farm_path(farm)),
                ("Resign And Return", lambda: resign_and_return(farm)),
            ]
        )

    elif farm.flow == FLOW_DIALOG:
        steps.extend(
            [
                (
                    "Enter Farm By Dialog",
                    lambda: BT.Sequence(
                        name="Enter Farm By Dialog",
                        children=[
                            BT.MoveAndDialog(
                                farm.entry_position,
                                dialog_id=farm.entry_dialog,
                                pause_on_combat=False,
                                log=True,
                                multi_account=False,
                            ),
                            BT.WaitForMapLoad(
                                map_id=farm.farm_map_id,
                                timeout_ms=45_000,
                            ),
                        ],
                    ),
                ),
                ("Farm Path", lambda: farm_path(farm)),
                ("Resign And Return", lambda: resign_and_return(farm)),
            ]
        )

    elif farm.flow == FLOW_FOW:
        steps.extend(
            [
                ("Enter Fissure Of Woe", lambda: enter_fow(farm)),
                ("Farm Path", lambda: farm_path(farm)),
                ("Resign And Return", lambda: resign_and_return(farm)),
            ]
        )

    else:
        raise ValueError(f"Unsupported Nicholas farm flow: {farm.flow}")

    return steps
