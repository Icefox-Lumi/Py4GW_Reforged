#region Imports
import math
import os
import sys
import traceback
from typing import Any
import Py4GW
import PyImGui
import PySystem

from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build

MODULE_NAME = "HeroAI"
MODULE_ICON = "Assets/Textures/Module_Icons/HeroAI.png"

from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.routines_src.BehaviourTrees import BehaviorTree

from Py4GWCoreLib.HeroAI.cache_data import CacheData
from Py4GWCoreLib.HeroAI.follow.follower_runtime import (
    FollowExecutionState,
    execute_follower_follow,
    get_follow_destination_distance,
    is_follow_recovery_active,
)
from Py4GWCoreLib.HeroAI import dispatch_diagnostics as _hbs_outer_diag
from Py4GWCoreLib.HeroAI import enemy_party
from Py4GWCoreLib.HeroAI import resurrection_scroll

from Py4GWCoreLib.HeroAI.windows import (HeroAI_FloatingWindows ,HeroAI_Windows,)
from Py4GWCoreLib.HeroAI.ui_base import HeroAI_BaseUI
from Py4GWCoreLib.HeroAI.ui import (draw_configure_window, draw_skip_cutscene_overlay)
from Py4GWCoreLib.HeroAI import team_viewer_broadcast
from Py4GWCoreLib import (GLOBAL_CACHE, Agent,
                          Range, Routines, ThrottledTimer, SharedCommandType)

#region GLOBALS
LOOT_THROTTLE_CHECK = ThrottledTimer(250)

cached_data = CacheData()
heroai_build = HeroAI_Build(cached_data)
map_quads : list[Map.Pathing.Quad] = []
#region Looting
def LootingNode(cached_data: CacheData)-> BehaviorTree.NodeState:
    options = cached_data.account_options
    if not options or not options.Looting:
        return BehaviorTree.NodeState.FAILURE

    if is_follow_recovery_active(cached_data, follow_execution_state):
        return BehaviorTree.NodeState.FAILURE
    
    if cached_data.data.in_aggro:
        return BehaviorTree.NodeState.FAILURE
    
    
    account_email = Player.GetAccountEmail()
    index, message = GLOBAL_CACHE.ShMem.PreviewNextMessage(account_email)

    if index != -1 and message and message.Command == SharedCommandType.PickUpLoot:
        if LOOT_THROTTLE_CHECK.IsExpired():
            return BehaviorTree.NodeState.FAILURE
        return BehaviorTree.NodeState.RUNNING
    
    if GLOBAL_CACHE.Inventory.GetFreeSlotCount() <= 1:
        return BehaviorTree.NodeState.FAILURE
    
    from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters import LootFilters

    loot_array = LootFilters().GetLootArray(Range.Earshot.value)

    if len(loot_array) == 0:
        return BehaviorTree.NodeState.FAILURE

    self_account = GLOBAL_CACHE.ShMem.GetAccountDataFromEmail(account_email)
    if self_account:
        GLOBAL_CACHE.ShMem.SendMessage(
            self_account.AccountEmail,
            self_account.AccountEmail,
            SharedCommandType.PickUpLoot,
            (0, 0, 0, 0),
        )
        LOOT_THROTTLE_CHECK.Reset()
        # Return RUNNING so the tree knows the task started
        return BehaviorTree.NodeState.RUNNING

    return BehaviorTree.NodeState.FAILURE




#region Combat
def HandleOutOfCombat(cached_data: CacheData):
    options = cached_data.account_options
    
    if not options or not options.Combat:  # halt operation if combat is disabled
        _outer_record_dispatch("ooc", reached=False, reason="combat_disabled")
        heroai_build.ResetTickExecution()
        return False
    
    if cached_data.data.in_aggro:
        _outer_record_dispatch("ooc", reached=False, reason="in_aggro")
        return False

    if is_follow_recovery_active(cached_data, follow_execution_state):
        _outer_record_dispatch("ooc", reached=False, reason="follow_recovery")
        heroai_build.ResetTickExecution()
        return False

    player_agent_id = Player.GetAgentID()
    in_casting_routine = cached_data.combat_handler.InCastingRoutine()
    player_casting = None
    if not in_casting_routine:
        player_casting = Agent.IsCasting(player_agent_id)
    if in_casting_routine or player_casting:
        _outer_record_dispatch("ooc", reached=False, reason="casting")
        return False

    _outer_record_dispatch("ooc", reached=True)
    heroai_build.set_cached_data(cached_data)
    next(heroai_build.Tick(is_in_combat=False), None)
    result = heroai_build.DidTickSucceed()
    _outer_record_dispatch(
        "ooc",
        reached=True,
        result=result,
        build_contract=_outer_build_contract_name(heroai_build),
    )
    return result

def HandleCombat(cached_data: CacheData):
    options = cached_data.account_options
    
    if not options or not options.Combat:  # halt operation if combat is disabled
        _outer_record_dispatch("combat", reached=False, reason="combat_disabled")
        heroai_build.ResetTickExecution()
        return False

    if is_follow_recovery_active(cached_data, follow_execution_state):
        _outer_record_dispatch("combat", reached=False, reason="follow_recovery")
        heroai_build.ResetTickExecution()
        return False
    
    if not cached_data.data.in_aggro:
        _outer_record_dispatch("combat", reached=False, reason="not_in_aggro")
        return False

    _outer_record_dispatch("combat", reached=True)
    heroai_build.set_cached_data(cached_data)
    next(heroai_build.Tick(is_in_combat=True), None)
    result = heroai_build.DidTickSucceed()
    _outer_record_dispatch(
        "combat",
        reached=True,
        result=result,
        build_contract=_outer_build_contract_name(heroai_build),
    )
    return result



#region Following
following_flag = False
follow_execution_state = FollowExecutionState()
FOLLOW_INI_FILENAMES = (
    "FollowModule_Formations.ini",
    "FollowModule_Settings.ini",
)
printed_widget_list = False


_OUTER_DIAGNOSTIC_OWNER = "widget"


_OUTER_DIAGNOSTIC_RUNTIME: dict[str, Any] = {
    "winning_branch": None,
    "last_branch": None,
    "last_branch_result": None,
    "guard_alive": None,
    "guard_distance_safe": None,
    "guard_reason": None,
    "guard_distance_bucket": None,
    "guard_recovery": None,
    "guard_not_knocked_down": None,
    "casting_blocked": None,
    "casting_in_routine": None,
    "casting_recovery": None,
    "player_casting": None,
    "movement_result": None,
    "movement_reason": None,
    "movement_moving": None,
    "movement_observed": False,
    "movement_condition": False,
    "follow_result": None,
    "follow_distance_bucket": None,
    "follow_recovery": None,
    "follow_stuck_mode": None,
    "dispatch_phase": None,
    "dispatch_reason": None,
    "semantic_dispatch_blocker": "none",
    "dispatch_reached": False,
    "dispatch_result": None,
    "build_contract": None,
    "movement_starvation": False,
    "movement_starvation_duration_ms": None,
    "movement_starvation_started_tick": None,
}


def _outer_distance_bucket(distance: Any) -> int | str | None:
    if not isinstance(distance, (int, float)):
        return None
    if not math.isfinite(distance):
        return "inf" if distance > 0 else "nan"
    return int(distance // 250)


def _outer_branch_name(name: str) -> str:
    return {
        "follow_action": "follow",
        "movement_interrupt_action": "movement_interrupt",
    }.get(name, name)


def _outer_build_contract_name(build: Any) -> str | None:
    try:
        contract_build = build.GetBuildContract()
        return str(getattr(contract_build, "build_name", "unknown"))
    except Exception:
        return None


def _outer_tick() -> int:
    try:
        return int(PySystem.get_tick_count64())
    except Exception:
        return 0


def _outer_begin_tree_tick() -> None:
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "winning_branch": None,
            "last_branch": None,
            "last_branch_result": None,
            "movement_observed": False,
            "movement_condition": False,
            "movement_result": None,
            "movement_reason": None,
            "movement_moving": None,
            "follow_result": None,
            "follow_distance_bucket": None,
            "dispatch_phase": None,
            "dispatch_reason": None,
            "dispatch_reached": False,
            "dispatch_result": None,
            "build_contract": None,
            "movement_starvation_duration_ms": None,
        }
    )
    _hbs_outer_diag.increment_counter(_OUTER_DIAGNOSTIC_OWNER, "bt_ticks")


def _outer_record_dispatch(
    phase: str,
    *,
    reached: bool,
    reason: str | None = None,
    result: Any = None,
    build_contract: str | None = None,
) -> None:
    was_reached = bool(_OUTER_DIAGNOSTIC_RUNTIME.get("dispatch_reached"))
    dispatch_reason = reason or "none"
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "dispatch_phase": phase,
            "dispatch_reason": dispatch_reason,
            "dispatch_reached": reached,
            "dispatch_result": result,
            "build_contract": build_contract,
        }
    )
    if reached or dispatch_reason in {"in_aggro", "not_in_aggro"}:
        _OUTER_DIAGNOSTIC_RUNTIME["semantic_dispatch_blocker"] = "none"
    elif dispatch_reason != "none":
        _OUTER_DIAGNOSTIC_RUNTIME["semantic_dispatch_blocker"] = dispatch_reason
    if reached and not was_reached:
        _hbs_outer_diag.increment_counter(
            _OUTER_DIAGNOSTIC_OWNER,
            "build_dispatch_attempts",
        )
        _hbs_outer_diag.increment_counter(
            _OUTER_DIAGNOSTIC_OWNER,
            f"{phase}_dispatch_attempts",
        )


def _outer_trace_action(name: str, action):
    _hbs_outer_diag.increment_counter(_OUTER_DIAGNOSTIC_OWNER, f"{name}_calls")
    result = action()
    result_name = _hbs_outer_diag.node_state(result)
    _OUTER_DIAGNOSTIC_RUNTIME["last_branch"] = _outer_branch_name(name)
    _OUTER_DIAGNOSTIC_RUNTIME["last_branch_result"] = result_name
    _hbs_outer_diag.increment_counter(
        _OUTER_DIAGNOSTIC_OWNER,
        f"{name}_{result_name}",
    )
    if result_name != "failure":
        branch_name = _outer_branch_name(name)
        if not (
            branch_name == "movement_interrupt"
            and not bool(getattr(cached_data.data, "in_aggro", False))
        ):
            _OUTER_DIAGNOSTIC_RUNTIME["winning_branch"] = branch_name
    return result


def _outer_guard_alive() -> bool:
    result = Agent.IsAlive(Player.GetAgentID())
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "guard_alive": result,
        }
    )
    return result


def _outer_guard_distance_safe() -> bool:
    destination_distance = get_follow_destination_distance(cached_data)
    if destination_distance < Range.SafeCompass.value:
        recovery_active = False
        result = True
        reason = "within_safe_distance"
    else:
        recovery_active = is_follow_recovery_active(
            cached_data,
            follow_execution_state,
        )
        result = bool(recovery_active)
        reason = "recovery_active" if result else "distance_unsafe"
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "guard_distance_safe": result,
            "guard_reason": reason,
            "guard_distance_bucket": _outer_distance_bucket(destination_distance),
            "guard_recovery": recovery_active,
        }
    )
    return result


def _outer_guard_not_knocked_down() -> bool:
    result = not Agent.IsKnockedDown(Player.GetAgentID())
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "guard_not_knocked_down": result,
        }
    )
    return result


def _outer_casting_block() -> BehaviorTree.NodeState:
    in_casting_routine = cached_data.combat_handler.InCastingRoutine()
    recovery_active = None
    blocked_by_routine = False
    if in_casting_routine:
        recovery_active = is_follow_recovery_active(
            cached_data,
            follow_execution_state,
        )
        blocked_by_routine = not recovery_active
    player_casting = None
    if not blocked_by_routine:
        player_casting = Agent.IsCasting(Player.GetAgentID())
    blocked = blocked_by_routine or bool(player_casting)
    result = (
        BehaviorTree.NodeState.RUNNING
        if blocked
        else BehaviorTree.NodeState.SUCCESS
    )
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "casting_blocked": blocked,
            "casting_in_routine": in_casting_routine,
            "casting_recovery": recovery_active,
            "player_casting": player_casting,
        }
    )
    if (
        not blocked
        and _OUTER_DIAGNOSTIC_RUNTIME.get("semantic_dispatch_blocker") == "casting"
    ):
        _OUTER_DIAGNOSTIC_RUNTIME["semantic_dispatch_blocker"] = "none"
    return result

def _follow_ini_paths() -> list[str]:
    base_path = os.path.join(
        PySystem.Console.get_projects_path(),
        "Settings",
        "Global",
        "HeroAI",
    )
    return [os.path.join(base_path, filename) for filename in FOLLOW_INI_FILENAMES]

def _follow_ini_ready() -> bool:
    return all(os.path.exists(path) for path in _follow_ini_paths())

def EnsureFollowModuleIni() -> None:
    if _follow_ini_ready():
        return

    try:
        from Py4GWCoreLib.HeroAI.follow.editor import _init_once
        _init_once()
    except Exception as e:
        PySystem.Console.Log(MODULE_NAME, f"Follow formation INI bootstrap failed: {e}", PySystem.Console.MessageType.Error)

def Follow(cached_data: CacheData) -> BehaviorTree.NodeState:
    if not cached_data.data.is_leader:
        result = execute_follower_follow(cached_data, follow_execution_state)
    else:
        result = BehaviorTree.NodeState.FAILURE  # leader doesn't follow anyone

    follow_recovery = bool(follow_execution_state.recovery_active)
    follow_stuck_mode = getattr(follow_execution_state.stuck, "mode", "unknown")
    destination_distance = None
    result_name = _hbs_outer_diag.node_state(result)
    if (
        follow_recovery
        or follow_stuck_mode != "idle"
        or result_name not in ("success", "failure")
    ):
        try:
            destination_distance = get_follow_destination_distance(cached_data)
        except Exception:
            destination_distance = None
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "follow_result": result_name,
            "follow_distance_bucket": _outer_distance_bucket(destination_distance),
            "follow_recovery": follow_recovery,
            "follow_stuck_mode": follow_stuck_mode,
        }
    )
    if (
        not follow_recovery
        and follow_stuck_mode == "idle"
        and _OUTER_DIAGNOSTIC_RUNTIME.get("semantic_dispatch_blocker")
        == "follow_recovery"
    ):
        _OUTER_DIAGNOSTIC_RUNTIME["semantic_dispatch_blocker"] = "none"
    return result

def handle_UI (cached_data: CacheData):
    global HeroAI_BT
    team_viewer_broadcast.tick()
    if not cached_data.ui_state_data.show_classic_controls:
        HeroAI_BaseUI.DrawEmbeddedWindow(cached_data)
    else:
        HeroAI_BaseUI.DrawControlPanelWindow(cached_data)
        if HeroAI_FloatingWindows.settings.ShowPartyPanelUI:
            HeroAI_BaseUI.DrawFollowerUI(cached_data)

    if HeroAI_BaseUI.show_debug:
        HeroAI_BaseUI.draw_debug_window(HeroAI_BT)

    HeroAI_FloatingWindows.show_ui(cached_data)
    if Map.IsExplorable() and cached_data.data.is_leader and enemy_party.is_enabled():
        enemy_party.ui_main()
    HeroAI_BaseUI.DrawBuildMatchesWindow(cached_data)
    HeroAI_BaseUI.DrawFollowFormationsQuickWindow(cached_data)
   
def initialize(cached_data: CacheData) -> bool:
    if not Routines.Checks.Map.MapValid():
        heroai_build.ClearBuildContract()
        return False
    
    if not GLOBAL_CACHE.Party.IsPartyLoaded():
        heroai_build.ResetTickExecution()
        return False
        
    if not Map.IsExplorable():  # halt operation if not in explorable area
        heroai_build.ClearBuildContract()
        return False

    if Map.IsInCinematic():  # halt operation during cinematic
        heroai_build.ResetTickExecution()
        return False
    
    HeroAI_BaseUI._process_flagging_runtime(cached_data)
    #HeroAI_FloatingWindows.draw_Targeting_floating_buttons(cached_data)     
    heroai_build.set_cached_data(cached_data)
    player_agent_id = Player.GetAgentID()
    if not Agent.IsAlive(player_agent_id) or Agent.IsKnockedDown(player_agent_id):
        heroai_build.ResetTickExecution()
    cached_data.UpdateCombat()
    return True

        
#region main  
#DEPRECATED FOR BEHAVIOUR TREE IMPLEMENTATION
#KEPT FOR REFERENCE
"""def UpdateStatus(cached_data: CacheData) -> bool:
    
    if (
            not Agent.IsAlive(Player.GetAgentID())
            or (HeroAI_FloatingWindows.DistanceToDestination(cached_data) >= Range.SafeCompass.value)
            or Agent.IsKnockedDown(Player.GetAgentID())
            or cached_data.combat_handler.InCastingRoutine()
            or Agent.IsCasting(Player.GetAgentID())
        ):
            return False

    
    if LootingRoutineActive():
        return True

    if HandleOutOfCombat(cached_data):
        return True

    if Agent.IsMoving(Player.GetAgentID()):
        return False

    if Loot(cached_data):
        return True

    if Follow(cached_data):
        cached_data.follow_throttle_timer.Reset()
        return True

    if HandleCombat(cached_data):
        cached_data.auto_attack_timer.Reset()
        return True

    return False"""

def IsUserInterrupting() -> bool:
    from Py4GWCoreLib.enums_src.IO_enums import Key
    io = PyImGui.get_io()
    
    if io.want_capture_keyboard or io.want_capture_mouse:
        return False
    
    movement_keys = [
        Key.W.value, Key.A.value, Key.S.value, Key.D.value,
        Key.Q.value, Key.E.value, Key.Z.value, Key.R.value,
        Key.UpArrow.value, Key.DownArrow.value, 
        Key.LeftArrow.value, Key.RightArrow.value
    ]
    
    for vk in movement_keys:
        if PyImGui.is_key_down(vk):
            return True

    if (PyImGui.is_mouse_down(0) and PyImGui.is_mouse_down(1)) or PyImGui.is_mouse_down(2):
        return True

    return False
    
    
GlobalGuardNode = BehaviorTree.SequenceNode(
    name="GlobalGuard",
    children=[
        BehaviorTree.ConditionNode(
            name="IsAlive",
            condition_fn=_outer_guard_alive,
        ),

        BehaviorTree.ConditionNode(
            name="DistanceSafe",
            condition_fn=_outer_guard_distance_safe,
        ),

        BehaviorTree.ConditionNode(
            name="NotKnockedDown",
            condition_fn=_outer_guard_not_knocked_down,
        ),
        
    ],
)
  
CastingBlockNode = BehaviorTree.ConditionNode(
    name="IsCasting",
    condition_fn=_outer_casting_block,
)

    
    
def movement_interrupt() -> BehaviorTree.NodeState:
    # During a smart unstuck detour, BT.Move must be ticked at full HeroAI
    # BT rate so it can steer the engine target continuously 
    is_moving = Agent.IsMoving(Player.GetAgentID())
    if follow_execution_state.stuck.mode != "idle":
        result = BehaviorTree.NodeState.FAILURE  # let Follow run every tick during detour
        reason = "smart_unstuck_active"
    elif is_moving:
        if cached_data.data.in_aggro:
            result = BehaviorTree.NodeState.FAILURE  # give combat/build dispatch a turn
            reason = "agent_moving_combat_yield"
        else:
            result = BehaviorTree.NodeState.SUCCESS   # block lower-priority automation for this tick
            reason = "agent_moving"
    else:
        result = BehaviorTree.NodeState.FAILURE      # allow next branch
        reason = "not_moving"
    _OUTER_DIAGNOSTIC_RUNTIME.update(
        {
            "movement_result": _hbs_outer_diag.node_state(result),
            "movement_reason": reason,
            "movement_moving": is_moving,
            "movement_observed": True,
            "movement_condition": bool(
                cached_data.data.in_aggro
                and result == BehaviorTree.NodeState.SUCCESS
                and reason == "agent_moving"
            ),
        }
    )
    return result


def user_interrupt() -> BehaviorTree.NodeState:
    #if IsUserInterrupting():
    #    return BehaviorTree.NodeState.SUCCESS   # block lower-priority automation for this tick
    return BehaviorTree.NodeState.FAILURE      # allow next branch


HeroAI_BT = BehaviorTree.SequenceNode(name="HeroAI_Main_BT",
    children=[
        # ---------- GLOBAL HARD GUARD ----------
        GlobalGuardNode,
        CastingBlockNode,

        # ---------- PRIORITY SELECTOR ----------
        BehaviorTree.SelectorNode(name="UpdateStatusSelector",
            children=[
                # Looting routine already active (allowed anytime)
                BehaviorTree.ActionNode(name="LootingRoutine",
                    action_fn=lambda: _outer_trace_action(
                        "looting",
                        lambda: LootingNode(cached_data),
                    ),
                ),

                # Out-of-combat behavior (allowed while moving)
                BehaviorTree.ActionNode(
                    name="HandleOutOfCombat",
                    action_fn=lambda: _outer_trace_action(
                        "ooc",
                        lambda: (
                            BehaviorTree.NodeState.SUCCESS
                            if HandleOutOfCombat(cached_data)
                            else BehaviorTree.NodeState.FAILURE
                        ),
                    ),
                ),

                # User / external movement override (blocks below)
                BehaviorTree.ActionNode(
                    name="UserInterrupt",
                    action_fn=lambda: _outer_trace_action(
                        "user_interrupt",
                        user_interrupt,
                    ),
                ),

                # Follow
                BehaviorTree.ActionNode(
                    name="Follow",
                    action_fn=lambda: _outer_trace_action(
                        "follow_action",
                        lambda: Follow(cached_data),
                    ),
                ),

                BehaviorTree.ActionNode(
                    name="MovementInterrupt",
                    action_fn=lambda: _outer_trace_action(
                        "movement_interrupt_action",
                        movement_interrupt,
                    ),
                ),

                # Combat
                BehaviorTree.ActionNode(
                    name="HandleCombat",
                    action_fn=lambda: _outer_trace_action(
                        "combat",
                        lambda: (
                            cached_data.auto_attack_timer.Reset()
                            or BehaviorTree.NodeState.SUCCESS
                            if HandleCombat(cached_data)
                            else BehaviorTree.NodeState.FAILURE
                        ),
                    ),
                ),
            ],
        ),
    ],
)


def _outer_log_tree_snapshot(tree_result: BehaviorTree.NodeState) -> None:
    try:
        fields = _hbs_outer_diag.cached_state_fields(cached_data)
        in_aggro = bool(fields.get("in_aggro"))
        runtime = _OUTER_DIAGNOSTIC_RUNTIME
        guard_alive = runtime.get("guard_alive")
        guard_distance_safe = runtime.get("guard_distance_safe")
        guard_not_knocked_down = runtime.get("guard_not_knocked_down")
        if guard_alive is False:
            guard = "blocked"
            guard_reason = "dead"
        elif guard_distance_safe is False:
            guard = "blocked"
            guard_reason = runtime.get("guard_reason") or "distance_unsafe"
        elif guard_not_knocked_down is False:
            guard = "blocked"
            guard_reason = "knocked_down"
        elif all(
            value is True
            for value in (guard_alive, guard_distance_safe, guard_not_knocked_down)
        ):
            guard = "pass"
            guard_reason = "none"
        else:
            guard = "unknown"
            guard_reason = "unknown"

        casting_blocked = runtime.get("casting_blocked")
        casting = (
            "blocked"
            if casting_blocked is True
            else "pass"
            if casting_blocked is False
            else "unknown"
        )
        branch = runtime.get("winning_branch")
        if branch is None:
            if guard == "blocked":
                branch = "global_guard"
            elif casting == "blocked":
                branch = "casting_guard"
            else:
                branch = "none"

        last_branch = runtime.get("last_branch")
        last_branch_result = runtime.get("last_branch_result")
        if (
            not in_aggro
            and last_branch == "movement_interrupt"
            and last_branch_result == "success"
        ):
            last_branch = "none"
            last_branch_result = "none"
        movement_result = runtime.get("movement_result") if in_aggro else "na"
        movement_reason = runtime.get("movement_reason") if in_aggro else "na"
        follow_active = branch == "follow"
        recovery_active = bool(
            runtime.get("follow_recovery")
            or runtime.get("guard_recovery")
        )
        stuck_mode = runtime.get("follow_stuck_mode")
        follow_result = runtime.get("follow_result") if follow_active else "na"
        follow_issue = bool(
            follow_active
            and (
                recovery_active
                or stuck_mode not in (None, "idle")
                or follow_result not in ("success", "failure")
            )
        )
        previous_starvation = bool(runtime.get("movement_starvation"))
        movement_observed = bool(runtime.get("movement_observed"))
        if movement_observed:
            starvation_active = bool(runtime.get("movement_condition"))
        elif (
            branch in {"ooc", "user_interrupt", "follow", "combat", "looting"}
            or runtime.get("dispatch_reached")
            or guard == "blocked"
            or casting == "blocked"
        ):
            starvation_active = False
        else:
            starvation_active = previous_starvation
        current_tick = _outer_tick()
        if starvation_active != previous_starvation:
            if starvation_active:
                runtime["movement_starvation_started_tick"] = current_tick
                runtime["movement_starvation_duration_ms"] = None
            else:
                started_tick = runtime.get("movement_starvation_started_tick")
                runtime["movement_starvation_duration_ms"] = (
                    max(0, current_tick - started_tick)
                    if isinstance(started_tick, int)
                    else None
                )
                runtime["movement_starvation_started_tick"] = None
            runtime["movement_starvation"] = starvation_active
        starvation_age_ms = None
        started_tick = runtime.get("movement_starvation_started_tick")
        if starvation_active and isinstance(started_tick, int):
            starvation_age_ms = max(0, current_tick - started_tick)
        semantic_dispatch_blocker = (
            runtime.get("semantic_dispatch_blocker") or "none"
        )
        semantic_owner = (
            "movement_starvation"
            if starvation_active
            else "global_guard"
            if guard == "blocked"
            else "casting_guard"
            if casting == "blocked"
            else "follow_recovery"
            if recovery_active or stuck_mode not in (None, "idle")
            else "dispatch_blocked"
            if semantic_dispatch_blocker != "none"
            else "none"
        )
        dispatch_reason = runtime.get("dispatch_reason") or "none"
        dispatch_result = runtime.get("dispatch_result")
        dispatch_failed = runtime.get("dispatch_reached") and dispatch_result is False
        fields = {
            "in_aggro": fields.get("in_aggro"),
            "local_aggro": fields.get("local_aggro"),
            "party_aggro": fields.get("party_aggro"),
            "leader_aggro": fields.get("leader_aggro"),
            "is_leader": fields.get("is_leader"),
            "following": fields.get("following"),
            "combat_enabled": fields.get("combat_enabled"),
            "branch": branch,
            "last_branch": last_branch,
            "last_branch_result": last_branch_result,
            "guard": guard,
            "guard_reason": guard_reason,
            "guard_alive": guard_alive,
            "guard_distance": guard_distance_safe,
            "guard_knocked": guard_not_knocked_down,
            "guard_distance_bucket": (
                runtime.get("guard_distance_bucket") if guard != "pass" else None
            ),
            "casting": casting,
            "casting_in_routine": runtime.get("casting_in_routine"),
            "casting_recovery": runtime.get("casting_recovery"),
            "player_casting": runtime.get("player_casting"),
            "recovery": recovery_active,
            "stuck_mode": stuck_mode,
            "dispatch_phase": runtime.get("dispatch_phase") or "none",
            "dispatch_reason": dispatch_reason,
            "dispatch_reached": bool(runtime.get("dispatch_reached")),
            "dispatch_result": dispatch_result,
            "build_contract": runtime.get("build_contract") or "none",
            "movement": movement_result,
            "movement_reason": movement_reason,
            "moving": runtime.get("movement_moving") if in_aggro else None,
            "follow_result": follow_result,
            "follow_distance_bucket": (
                runtime.get("follow_distance_bucket") if follow_issue else None
            ),
            "movement_starvation": starvation_active,
            "movement_starvation_age_ms": starvation_age_ms,
            "movement_starvation_duration_ms": runtime.get(
                "movement_starvation_duration_ms"
            ),
            "semantic_owner": semantic_owner,
            "semantic_dispatch_blocker": semantic_dispatch_blocker,
            "destination_bucket": (
                runtime.get("follow_distance_bucket")
                if follow_issue
                else runtime.get("guard_distance_bucket")
                if guard != "pass"
                else None
            ),
        }
        interesting = bool(
            starvation_active
            or follow_issue
            or guard != "pass"
            or casting == "blocked"
            or semantic_dispatch_blocker != "none"
            or dispatch_failed
            or bool(runtime.get("dispatch_reached"))
        )
        semantic_fields = {
            "in_aggro": fields["in_aggro"],
            "local_aggro": fields["local_aggro"],
            "party_aggro": fields["party_aggro"],
            "leader_aggro": fields["leader_aggro"],
            "following": fields["following"],
            "combat_enabled": fields["combat_enabled"],
            "guard": guard,
            "casting": casting,
            "recovery": recovery_active,
            "stuck_mode": stuck_mode,
            "movement_starvation": starvation_active,
            "semantic_owner": semantic_owner,
            "semantic_dispatch_blocker": semantic_dispatch_blocker,
        }
        _hbs_outer_diag.log_compact_state(
            _OUTER_DIAGNOSTIC_OWNER,
            fields,
            semantic_fields=semantic_fields,
            interesting=interesting,
        )
    except Exception:
        return


#region real_main
def configure():
    draw_configure_window(MODULE_NAME, HeroAI_FloatingWindows.configure_window)
    
def tooltip():
    import PyImGui
    from Py4GWCoreLib.py4gwcorelib_src.Color import Color
    from Py4GWCoreLib.ImGui import ImGui
    PyImGui.begin_tooltip()

    # Title
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored("HeroAI: Multibox Combat Engine", title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.spacing()
    PyImGui.separator()

    # Description
    PyImGui.text("An advanced multi-account synchronization and combat AI system.")
    PyImGui.text("This widget transforms extra game instances into intelligent,")
    PyImGui.text("automated party members that behave like high-performance heroes.")
    PyImGui.spacing()

    # Features
    PyImGui.text_colored("Features:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Multibox Logic: Synchronizes actions across multiple game clients")
    PyImGui.bullet_text("Advanced AI: Replaces standard hero behavior with custom combat routines")
    PyImGui.bullet_text("Intelligent interrupt logic, hex removal, enemy tracking, and more")
    PyImGui.bullet_text("Formation Control: Dynamic follower distancing and tactical positioning")
    PyImGui.bullet_text("Automation Suite: Integrated auto-looting, salvaging, and cutscene skipping")
    PyImGui.bullet_text("Behavior Trees: Complex decision-making for combat and out-of-combat states")
    PyImGui.bullet_text("Shared Memory: Seamless data exchange via the Shared Memory Manager (SMM)")

    PyImGui.spacing()
    PyImGui.separator()
    PyImGui.spacing()

    # Credits
    PyImGui.text_colored("Credits:", title_color.to_tuple_normalized())
    PyImGui.bullet_text("Developed by Apo")
    PyImGui.bullet_text("Contributors: Mark, frenkey, Dharmantrix, aC, Greg-76, ")
    PyImGui.bullet_text("Sloppynacho, Wick-Divinus, LLYANL, Zilvereyes, valkogw")

    PyImGui.end_tooltip()

modulo = 0

def main():
    global cached_data, map_quads, modulo
    
    try:
        _hbs_outer_diag.set_active_owner(_OUTER_DIAGNOSTIC_OWNER)
        cached_data.Update()

        EnsureFollowModuleIni()
        HeroAI_FloatingWindows.update()
        handle_UI(cached_data)
        resurrection_scroll.tick()
        
        if initialize(cached_data):
            modulo += 1
            if modulo >= 2:
                modulo = 0
                _outer_begin_tree_tick()
                tree_result = HeroAI_BT.tick()
                _outer_log_tree_snapshot(tree_result)
        else:
            _hbs_outer_diag.log_compact_state(
                _OUTER_DIAGNOSTIC_OWNER,
                {
                    **_hbs_outer_diag.cached_state_fields(cached_data),
                    "branch": "initialize",
                    "init": "rejected",
                },
            )
            map_quads.clear()
            HeroAI_BT.reset()



    except ImportError as e:
        PySystem.Console.Log(MODULE_NAME, f"ImportError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except ValueError as e:
        PySystem.Console.Log(MODULE_NAME, f"ValueError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except TypeError as e:
        PySystem.Console.Log(MODULE_NAME, f"TypeError encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    except Exception as e:
        # Catch-all for any other unexpected exceptions
        PySystem.Console.Log(MODULE_NAME, f"Unexpected error encountered: {str(e)}", PySystem.Console.MessageType.Error)
        PySystem.Console.Log(MODULE_NAME, f"Stack trace: {traceback.format_exc()}", PySystem.Console.MessageType.Error)
    finally:
        pass

def minimal():    
    draw_skip_cutscene_overlay()

def on_enable():
    heroai_build.ClearBuildContract()
    HeroAI_FloatingWindows.settings.reset()
    HeroAI_FloatingWindows.SETTINGS_THROTTLE.SetThrottleTime(50)

__all__ = ['main', 'configure', 'on_enable']
