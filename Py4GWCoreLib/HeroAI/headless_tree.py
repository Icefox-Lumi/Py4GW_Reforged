import math
from typing import Any

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Routines import Routines
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.routines_src.BehaviourTrees import BehaviorTree
from Py4GWCoreLib import ActionQueueManager, Range, SharedCommandType, ThrottledTimer, Utils
from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters import LootFilters

from .cache_data import CacheData
from . import dispatch_diagnostics as _hbs_outer_diag
from .follow.follower_runtime import (
    FollowExecutionState,
    execute_follower_follow,
    get_follow_destination_distance,
    is_follow_recovery_active,
)
from . import resurrection_scroll
from .settings import Settings
from .utils import DrawSharedMemoryFlags


class HeroAIHeadlessTree:
    """
    Headless HeroAI upkeep/combat tree.

    This keeps the non-UI parts of the HeroAI widget tree available to scripts
    without requiring the widget itself to be enabled.
    """

    def __init__(self, cached_data: CacheData | None = None, heroai_build: HeroAI_Build | None = None):
        self.cached_data = cached_data or CacheData()
        self.heroai_build = heroai_build or HeroAI_Build(self.cached_data)
        Settings().AutoCallTargets = True
        self._loot_throttle_check = ThrottledTimer(250)
        self._looting_node: BehaviorTree.ActionNode | None = None
        self._status_selector: BehaviorTree.SelectorNode | None = None
        self._follow_state = FollowExecutionState()
        self._headless_looting_enabled = True
        self._headless_combat_enabled = True
        self._outer_runtime: dict[str, Any] = {
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
        }
        self.tree = self._build_tree()

    @staticmethod
    def _outer_distance_bucket(distance: Any) -> int | str | None:
        if not isinstance(distance, (int, float)):
            return None
        if not math.isfinite(distance):
            return "inf" if distance > 0 else "nan"
        return int(distance // 250)

    @staticmethod
    def _outer_branch_name(name: str) -> str:
        return "follow" if name == "follow_action" else name

    @staticmethod
    def _outer_build_contract_name(build: Any) -> str | None:
        try:
            contract_build = build.GetBuildContract()
            return str(getattr(contract_build, "build_name", "unknown"))
        except Exception:
            return None

    def _outer_begin_tree_tick(self) -> None:
        self._outer_runtime.update(
            {
                "winning_branch": None,
                "last_branch": None,
                "last_branch_result": None,
                "follow_result": None,
                "follow_distance_bucket": None,
                "dispatch_phase": None,
                "dispatch_reason": None,
                "dispatch_reached": False,
                "dispatch_result": None,
                "build_contract": None,
            }
        )
        _hbs_outer_diag.increment_counter("headless", "bt_ticks")

    def _outer_record_dispatch(
        self,
        phase: str,
        *,
        reached: bool,
        reason: str | None = None,
        result: Any = None,
        build_contract: str | None = None,
    ) -> None:
        was_reached = bool(self._outer_runtime.get("dispatch_reached"))
        dispatch_reason = reason or "none"
        self._outer_runtime.update(
            {
                "dispatch_phase": phase,
                "dispatch_reason": dispatch_reason,
                "dispatch_reached": reached,
                "dispatch_result": result,
                "build_contract": build_contract,
            }
        )
        if reached:
            self._outer_runtime["semantic_dispatch_blocker"] = "none"
        elif dispatch_reason != "none":
            self._outer_runtime["semantic_dispatch_blocker"] = dispatch_reason
        if reached and not was_reached:
            _hbs_outer_diag.increment_counter(
                "headless",
                "build_dispatch_attempts",
            )
            _hbs_outer_diag.increment_counter(
                "headless",
                f"{phase}_dispatch_attempts",
            )

    def _outer_trace_action(self, name: str, action):
        _hbs_outer_diag.increment_counter("headless", f"{name}_calls")
        result = action()
        result_name = _hbs_outer_diag.node_state(result)
        self._outer_runtime["last_branch"] = self._outer_branch_name(name)
        self._outer_runtime["last_branch_result"] = result_name
        _hbs_outer_diag.increment_counter(
            "headless",
            f"{name}_{result_name}",
        )
        if result_name != "failure":
            self._outer_runtime["winning_branch"] = self._outer_branch_name(name)
        return result

    def _outer_guard_alive(self) -> bool:
        result = Agent.IsAlive(Player.GetAgentID())
        self._outer_runtime.update(
            {
                "guard_alive": result,
            }
        )
        return result

    def _outer_guard_distance_safe(self) -> bool:
        destination_distance = self._distance_to_destination()
        if destination_distance < Range.SafeCompass.value:
            recovery_active = False
            result = True
            reason = "within_safe_distance"
        else:
            recovery_active = is_follow_recovery_active(
                self.cached_data,
                self._follow_state,
            )
            result = bool(recovery_active)
            reason = "recovery_active" if result else "distance_unsafe"
        self._outer_runtime.update(
            {
                "guard_distance_safe": result,
                "guard_reason": reason,
                "guard_distance_bucket": self._outer_distance_bucket(destination_distance),
                "guard_recovery": recovery_active,
            }
        )
        return result

    def _outer_guard_not_knocked_down(self) -> bool:
        result = not Agent.IsKnockedDown(Player.GetAgentID())
        self._outer_runtime.update(
            {
                "guard_not_knocked_down": result,
            }
        )
        return result

    def _outer_casting_block(self) -> BehaviorTree.NodeState:
        in_casting_routine = self.cached_data.combat_handler.InCastingRoutine()
        recovery_active = None
        blocked_by_routine = False
        if in_casting_routine:
            recovery_active = is_follow_recovery_active(
                self.cached_data,
                self._follow_state,
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
        self._outer_runtime.update(
            {
                "casting_blocked": blocked,
                "casting_in_routine": in_casting_routine,
                "casting_recovery": recovery_active,
                "player_casting": player_casting,
            }
        )
        if (
            not blocked
            and self._outer_runtime.get("semantic_dispatch_blocker") == "casting"
        ):
            self._outer_runtime["semantic_dispatch_blocker"] = "none"
        return result

    def SetCombatEnabled(self, enabled: bool) -> None:
        self._headless_combat_enabled = bool(enabled)

    def IsCombatEnabled(self) -> bool:
        return bool(self._headless_combat_enabled)

    def _has_active_pick_up_loot_message(self) -> bool:
        account_email = Player.GetAccountEmail()
        index, message = GLOBAL_CACHE.ShMem.PreviewNextMessage(account_email)
        return bool(index != -1 and message and message.Command == SharedCommandType.PickUpLoot)

    def _consume_headless_looting_control_messages(self) -> None:
        account_email = str(Player.GetAccountEmail() or '').strip()
        if not account_email:
            return

        latest_enabled: bool | None = None
        for message_index, message in GLOBAL_CACHE.ShMem.GetAllMessages():
            if message is None:
                continue
            if not getattr(message, 'Active', False):
                continue
            if str(getattr(message, 'ReceiverEmail', '') or '').strip() != account_email:
                continue
            if int(getattr(message, 'Command', SharedCommandType.NoCommand)) != int(SharedCommandType.SetHeadlessLooting):
                continue
            latest_enabled = bool(int(getattr(message, 'Params', (1, 0, 0, 0))[0] or 0))
            GLOBAL_CACHE.ShMem.MarkMessageAsFinished(account_email, message_index)

        if latest_enabled is not None:
            self._headless_looting_enabled = latest_enabled

    def _is_looting_routine_active(self) -> bool:
        if not self._headless_looting_enabled:
            return False

        if self.cached_data.IsHeadlessCombatPauseActive():
            return False

        if not self._has_active_pick_up_loot_message():
            return False

        if self._loot_throttle_check.IsExpired():
            return False

        return True

    def _handle_looting(self) -> BehaviorTree.NodeState:
        if not self._headless_looting_enabled:
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        if is_follow_recovery_active(self.cached_data, self._follow_state):
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        if self.cached_data.IsHeadlessCombatPauseActive():
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        if self._has_active_pick_up_loot_message():
            self.cached_data.in_looting_routine = True
            if not Routines.Checks.Map.MapValid() or not Map.IsExplorable():
                self.cached_data.in_looting_routine = False
                return BehaviorTree.NodeState.FAILURE
            if GLOBAL_CACHE.Inventory.GetFreeSlotCount() <= 1:
                self.cached_data.in_looting_routine = False
                return BehaviorTree.NodeState.FAILURE
            if self._loot_throttle_check.IsExpired():
                self.cached_data.in_looting_routine = False
                return BehaviorTree.NodeState.FAILURE
            return BehaviorTree.NodeState.RUNNING

        if not Routines.Checks.Map.MapValid() or not Map.IsExplorable():
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        if GLOBAL_CACHE.Inventory.GetFreeSlotCount() <= 1:
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        loot_array = LootFilters().GetLootArray(Range.Earshot.value)
        if len(loot_array) == 0:
            self.cached_data.in_looting_routine = False
            return BehaviorTree.NodeState.FAILURE

        account_email = Player.GetAccountEmail()
        self_account = GLOBAL_CACHE.ShMem.GetAccountDataFromEmail(account_email)
        if self_account:
            GLOBAL_CACHE.ShMem.SendMessage(
                self_account.AccountEmail,
                self_account.AccountEmail,
                SharedCommandType.PickUpLoot,
                (0, 0, 0, 0),
            )
            self._loot_throttle_check.Reset()
            self.cached_data.in_looting_routine = True
            return BehaviorTree.NodeState.RUNNING

        self.cached_data.in_looting_routine = False
        return BehaviorTree.NodeState.FAILURE

    def _handle_out_of_combat(self) -> bool:
        if not self._headless_combat_enabled:
            self._outer_record_dispatch(
                "ooc",
                reached=False,
                reason="headless_combat_disabled",
            )
            return False

        options = self.cached_data.account_options
        if not options or not options.Combat:
            self._outer_record_dispatch(
                "ooc",
                reached=False,
                reason="combat_disabled",
            )
            self.heroai_build.ResetTickExecution()
            return False

        if self.cached_data.IsHeadlessCombatPauseActive():
            self._outer_record_dispatch(
                "ooc",
                reached=False,
                reason="combat_pause_active",
            )
            return False

        if is_follow_recovery_active(self.cached_data, self._follow_state):
            self._outer_record_dispatch(
                "ooc",
                reached=False,
                reason="follow_recovery",
            )
            self.heroai_build.ResetTickExecution()
            return False

        player_agent_id = Player.GetAgentID()
        in_casting_routine = self.cached_data.combat_handler.InCastingRoutine()
        player_casting = None
        if not in_casting_routine:
            player_casting = Agent.IsCasting(player_agent_id)
        if in_casting_routine or player_casting:
            self._outer_record_dispatch("ooc", reached=False, reason="casting")
            return False

        self._outer_record_dispatch("ooc", reached=True)
        self.heroai_build.set_cached_data(self.cached_data)
        next(self.heroai_build.Tick(is_in_combat=False), None)
        result = self.heroai_build.DidTickSucceed()
        self._outer_record_dispatch(
            "ooc",
            reached=True,
            result=result,
            build_contract=self._outer_build_contract_name(self.heroai_build),
        )
        return result

    def _handle_combat(self) -> bool:
        if not self._headless_combat_enabled:
            self._outer_record_dispatch(
                "combat",
                reached=False,
                reason="headless_combat_disabled",
            )
            return False

        options = self.cached_data.account_options
        if not options or not options.Combat:
            self._outer_record_dispatch(
                "combat",
                reached=False,
                reason="combat_disabled",
            )
            self.heroai_build.ResetTickExecution()
            return False

        if is_follow_recovery_active(self.cached_data, self._follow_state):
            self._outer_record_dispatch(
                "combat",
                reached=False,
                reason="follow_recovery",
            )
            self.heroai_build.ResetTickExecution()
            return False

        if not self.cached_data.IsHeadlessCombatPauseActive():
            self._outer_record_dispatch(
                "combat",
                reached=False,
                reason="combat_pause_inactive",
            )
            return False

        self._outer_record_dispatch("combat", reached=True)
        self.heroai_build.set_cached_data(self.cached_data)
        next(self.heroai_build.Tick(is_in_combat=True), None)
        result = self.heroai_build.DidTickSucceed()
        self._outer_record_dispatch(
            "combat",
            reached=True,
            result=result,
            build_contract=self._outer_build_contract_name(self.heroai_build),
        )
        return result

    def _distance_to_destination(self) -> float:
        return get_follow_destination_distance(self.cached_data)

    def _is_user_interrupting(self) -> bool:
        return False

    def IsUserInterrupting(self) -> bool:
        return self._is_user_interrupting()

    def _follow(self) -> BehaviorTree.NodeState:
        result = execute_follower_follow(self.cached_data, self._follow_state)
        follow_recovery = bool(self._follow_state.recovery_active)
        follow_stuck_mode = getattr(self._follow_state.stuck, "mode", "unknown")
        result_name = _hbs_outer_diag.node_state(result)
        destination_distance = None
        if (
            follow_recovery
            or follow_stuck_mode != "idle"
            or result_name not in ("success", "failure")
        ):
            destination_distance = self._distance_to_destination()
        self._outer_runtime.update(
            {
                "follow_result": result_name,
                "follow_distance_bucket": self._outer_distance_bucket(
                    destination_distance
                ),
                "follow_recovery": follow_recovery,
                "follow_stuck_mode": follow_stuck_mode,
            }
        )
        if (
            not follow_recovery
            and follow_stuck_mode == "idle"
            and self._outer_runtime.get("semantic_dispatch_blocker")
            == "follow_recovery"
        ):
            self._outer_runtime["semantic_dispatch_blocker"] = "none"
        return result

    def IsLootingActive(self) -> bool:
        return bool(self._headless_looting_enabled) and self._is_looting_routine_active()

    def IsLootingNodeRunning(self) -> bool:
        if self._looting_node is None:
            return False
        return self._looting_node.last_state == BehaviorTree.NodeState.RUNNING

    def SetLootingEnabled(self, enabled: bool) -> None:
        self._headless_looting_enabled = bool(enabled)

    def IsLootingEnabled(self) -> bool:
        return bool(self._headless_looting_enabled)

    def SetResurrectionScrollEnabled(self, enabled: bool) -> None:
        Settings().set_account_resurrection_scroll_enabled(bool(enabled))

    def IsResurrectionScrollEnabled(self) -> bool:
        return bool(Settings().get_account_resurrection_scroll_enabled())

    def GetBuildContract(self):
        return self.heroai_build.GetBuildContract()

    def GetBuildContractName(self) -> str:
        contract_build = self.GetBuildContract()
        if contract_build is None:
            return ""
        return str(getattr(contract_build, "build_name", "") or contract_build.__class__.__name__)

    def initialize(self) -> bool:
        if not Routines.Checks.Map.MapValid():
            self.heroai_build.ClearBuildContract()
            return False

        if not GLOBAL_CACHE.Party.IsPartyLoaded():
            self.heroai_build.ResetTickExecution()
            return False

        if not Map.IsExplorable():
            self.heroai_build.ClearBuildContract()
            return False

        if Map.IsInCinematic():
            self.heroai_build.ResetTickExecution()
            return False

        player_agent_id = Player.GetAgentID()
        if not Agent.IsAlive(player_agent_id) or Agent.IsKnockedDown(player_agent_id):
            self.heroai_build.ResetTickExecution()

        self.heroai_build.set_cached_data(self.cached_data)
        self.cached_data.UpdateCombat()
        return True

    def update(self) -> None:
        self._consume_headless_looting_control_messages()
        resurrection_scroll.tick()
        self.cached_data.Update()

    def tick(self):
        _hbs_outer_diag.set_active_owner("headless")
        self.update()
        try:
            DrawSharedMemoryFlags()
        except Exception:
            pass
        if self.initialize():
            self._outer_begin_tree_tick()
            tree_result = self.tree.tick()
            self._outer_log_tree_snapshot(tree_result)
            return tree_result

        _hbs_outer_diag.log_compact_state(
            "headless",
            {
                **_hbs_outer_diag.cached_state_fields(self.cached_data),
                "branch": "initialize",
                "init": "rejected",
            },
        )
        self.tree.reset()
        return BehaviorTree.NodeState.RUNNING

    def reset(self) -> None:
        self.tree.reset()
        self.heroai_build.ClearBuildContract()
        self._follow_state = FollowExecutionState()
        self._headless_combat_enabled = True

    def _build_tree(self):
        self._looting_node = BehaviorTree.ActionNode(
            name="LootingRoutine",
            action_fn=lambda: self._outer_trace_action(
                "looting",
                lambda: self._handle_looting()
                if self._headless_looting_enabled
                else BehaviorTree.NodeState.FAILURE,
            ),
        )
        self._status_selector = BehaviorTree.SelectorNode(
            name="HeadlessHeroAI_UpdateStatusSelector",
            children=[
                self._looting_node,
                BehaviorTree.ActionNode(
                    name="HandleOutOfCombat",
                    action_fn=lambda: self._outer_trace_action(
                        "ooc",
                        lambda: (
                            BehaviorTree.NodeState.SUCCESS
                            if self._handle_out_of_combat()
                            else BehaviorTree.NodeState.FAILURE
                        ),
                    ),
                ),
                BehaviorTree.ActionNode(
                    name="Follow",
                    action_fn=lambda: self._outer_trace_action(
                        "follow_action",
                        self._follow,
                    ),
                ),
                BehaviorTree.ActionNode(
                    name="HandleCombat",
                    action_fn=lambda: self._outer_trace_action(
                        "combat",
                        lambda: (
                            self.cached_data.auto_attack_timer.Reset()
                            or BehaviorTree.NodeState.SUCCESS
                            if self._handle_combat()
                            else BehaviorTree.NodeState.FAILURE
                        ),
                    ),
                ),
            ],
        )

        global_guard = BehaviorTree.SequenceNode(
            name="HeadlessHeroAI_GlobalGuard",
            children=[
                BehaviorTree.ConditionNode(
                    name="IsAlive",
                    condition_fn=self._outer_guard_alive,
                ),
                BehaviorTree.ConditionNode(
                    name="DistanceSafe",
                    condition_fn=self._outer_guard_distance_safe,
                ),
                BehaviorTree.ConditionNode(
                    name="NotKnockedDown",
                    condition_fn=self._outer_guard_not_knocked_down,
                ),
            ],
        )

        casting_block = BehaviorTree.ConditionNode(
            name="IsCasting",
            condition_fn=self._outer_casting_block,
        )

        return BehaviorTree.SequenceNode(
            name="HeadlessHeroAI_Main_BT",
            children=[
                global_guard,
                casting_block,
                self._status_selector,
            ],
        )

    def _outer_log_tree_snapshot(self, tree_result: BehaviorTree.NodeState) -> None:
        try:
            cached_fields = _hbs_outer_diag.cached_state_fields(self.cached_data)
            in_aggro = bool(cached_fields.get("in_aggro"))
            runtime = self._outer_runtime
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
            dispatch_reason = runtime.get("dispatch_reason") or "none"
            dispatch_result = runtime.get("dispatch_result")
            dispatch_failed = runtime.get("dispatch_reached") and dispatch_result is False
            follow_active = branch == "follow"
            recovery_active = bool(
                runtime.get("follow_recovery")
                or runtime.get("guard_recovery")
            )
            follow_result = runtime.get("follow_result") if follow_active else "na"
            follow_issue = bool(
                follow_active
                and (
                    recovery_active
                    or runtime.get("follow_stuck_mode") not in (None, "idle")
                    or follow_result not in ("success", "failure")
                )
            )
            semantic_dispatch_blocker = (
                runtime.get("semantic_dispatch_blocker") or "none"
            )
            semantic_owner = (
                "global_guard"
                if guard == "blocked"
                else "casting_guard"
                if casting == "blocked"
                else "follow_recovery"
                if recovery_active or runtime.get("follow_stuck_mode") not in (None, "idle")
                else "dispatch_blocked"
                if semantic_dispatch_blocker != "none"
                else "none"
            )
            fields = {
                "in_aggro": cached_fields.get("in_aggro"),
                "local_aggro": cached_fields.get("local_aggro"),
                "party_aggro": cached_fields.get("party_aggro"),
                "leader_aggro": cached_fields.get("leader_aggro"),
                "is_leader": cached_fields.get("is_leader"),
                "following": cached_fields.get("following"),
                "combat_enabled": cached_fields.get("combat_enabled"),
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
                "stuck_mode": runtime.get("follow_stuck_mode"),
                "dispatch_phase": runtime.get("dispatch_phase") or "none",
                "dispatch_reason": dispatch_reason,
                "dispatch_reached": bool(runtime.get("dispatch_reached")),
                "dispatch_result": dispatch_result,
                "build_contract": runtime.get("build_contract") or "none",
                "follow_result": follow_result,
                "follow_distance_bucket": (
                    runtime.get("follow_distance_bucket") if follow_issue else None
                ),
                "movement_starvation": False,
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
                follow_issue
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
                "stuck_mode": runtime.get("follow_stuck_mode"),
                "movement_starvation": False,
                "semantic_owner": semantic_owner,
                "semantic_dispatch_blocker": semantic_dispatch_blocker,
            }
            _hbs_outer_diag.log_compact_state(
                "headless",
                fields,
                semantic_fields=semantic_fields,
                interesting=interesting,
            )
        except Exception:
            return
