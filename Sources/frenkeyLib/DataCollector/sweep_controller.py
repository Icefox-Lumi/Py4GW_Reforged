from dataclasses import dataclass
from typing import Any, Callable, Iterable

import Py4GW
import PySystem
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Py4GWcorelib import Utils
from Py4GWCoreLib.Routines import Routines


@dataclass
class SweepStatus:
    is_running: bool = False
    stop_requested: bool = False
    status: str = 'Idle'
    current_name: str = ''
    current_index: int = 0
    total: int = 0


class CrafterSweepController:
    def __init__(self, module_name: str = 'Data Collection Helper'):
        self.module_name = module_name
        self.state = SweepStatus()

    def set_module_name(self, module_name: str):
        self.module_name = module_name

    def set_status(self, status: str, crafter_name: str = '', current_index: int = 0, total: int = 0):
        self.state.status = status
        self.state.current_name = crafter_name
        self.state.current_index = current_index
        self.state.total = total

    def finish(self, status: str):
        self.state.is_running = False
        self.state.stop_requested = False
        self.set_status(status)

    def start(
        self,
        crafters: Iterable[Any],
        append_coroutine: Callable[[Any], None],
        on_collection_success: Callable[[Any], None],
    ) -> bool:
        if self.state.is_running:
            return False

        crafter_list = list(crafters)
        if not crafter_list:
            self.set_status('No unlocked auto-reachable crafters found.')
            return False

        self.state.is_running = True
        self.state.stop_requested = False
        self.set_status('Starting crafter sweep...', total=len(crafter_list))
        append_coroutine(self.run_sweep(crafter_list, on_collection_success))
        return True

    def request_stop(self, clear_coroutines: Callable[[], None] | None = None):
        if clear_coroutines is not None:
            clear_coroutines()
        if not self.state.is_running:
            return

        self.state.stop_requested = True
        self.set_status(
            'Stopping after current step...',
            self.state.current_name,
            self.state.current_index,
            self.state.total,
        )

    def run_sweep(self, crafters: list[Any], on_collection_success: Callable[[Any], None]):
        total = len(crafters)
        closed_count = 0

        for index, crafter in enumerate(crafters, start=1):
            if self.state.stop_requested:
                self.finish(f'Sweep stopped ({closed_count}/{total} completed).')
                return

            map_id = crafter.GetDisplayMapID()
            position = crafter.GetDisplayPosition()
            map_name = Map.GetMapName(map_id)
            self.set_status(f'Traveling to {map_name}...', crafter.name, index, total)

            if Map.GetBaseMapID() != Map.GetBaseMapID(map_id):
                travel_success = yield from Routines.Yield.Map.TravelToOutpost(map_id, timeout=20000, log=False)
                if not travel_success:
                    PySystem.Console.Log(
                        self.module_name,
                        f"Skipping '{crafter.name}' because travel to '{map_name}' failed.",
                        PySystem.Console.MessageType.Warning,
                    )
                    continue

                yield from Routines.Yield.wait(500, break_on_map_transition=True)

            if self.state.stop_requested:
                self.finish(f'Sweep stopped ({closed_count}/{total} completed).')
                return

            self.set_status('Walking to crafter...', crafter.name, index, total)
            distance_to_crafter = Utils.Distance(Player.GetXY(), position)
            timeout_ms = int(distance_to_crafter * 12)
            PySystem.Console.Log(
                self.module_name,
                f"Distance to '{crafter.name}' is {distance_to_crafter:.1f}. Allowing up to {timeout_ms} ms for movement.",
                PySystem.Console.MessageType.Info,
            )

            move_success = yield from Routines.Yield.Movement.FollowPath(
                [position],
                tolerance=200,
                timeout=timeout_ms,
                log=False,
            )
            if not move_success:
                PySystem.Console.Log(
                    self.module_name,
                    f"Skipping '{crafter.name}' because movement to the stored position failed.",
                    PySystem.Console.MessageType.Warning,
                )
                continue

            self.set_status(f"Opening {crafter.service_label().lower()} window...", crafter.name, index, total)
            window_opened = yield from self.open_crafter_window(crafter)
            if not window_opened:
                PySystem.Console.Log(
                    self.module_name,
                    f"Skipping '{crafter.name}' because the service window did not open.",
                    PySystem.Console.MessageType.Warning,
                )
                continue

            self.set_status('Waiting for window contents...', crafter.name, index, total)
            yield from Routines.Yield.wait(500)

            self.set_status(f"Collecting visible {crafter.service_label().lower()} data...", crafter.name, index, total)
            try:
                collected = yield from self.collect_crafter_data_with_retries(crafter)
                if collected:
                    on_collection_success(crafter)
            except Exception as exc:
                PySystem.Console.Log(
                    self.module_name,
                    f"Skipping '{crafter.name}' because data collection failed: {exc}",
                    PySystem.Console.MessageType.Warning,
                )
                continue

            self.set_status('Service window open, waiting 2 seconds...', crafter.name, index, total)
            yield from Routines.Yield.wait(2000)
            crafter.CloseCrafter()
            yield from Routines.Yield.wait(500)
            closed_count += 1

        self.finish(f'Sweep complete ({closed_count}/{total} windows opened).')

    def open_crafter_window(self, crafter: Any, timeout_ms: int = 1500):
        elapsed = 0
        retry_interval = 250
        reissue_interval = 1000
        since_reissue = reissue_interval

        while elapsed <= timeout_ms:
            if self.state.stop_requested:
                return False

            if not crafter.CanInteract():
                PySystem.Console.Log(
                    self.module_name,
                    f"Skipping '{crafter.name}' because your character does not currently meet {crafter.interaction_label()}.",
                    PySystem.Console.MessageType.Warning,
                )
                return False

            if crafter._service_window_is_open():
                return True

            agent_id = crafter.GetAgentId()
            if agent_id == 0:
                yield from Routines.Yield.wait(retry_interval)
                elapsed += retry_interval
                since_reissue += retry_interval
                continue

            if since_reissue >= reissue_interval:
                yield from Routines.Yield.Agents.ChangeTarget(agent_id)
                yield from Routines.Yield.Agents.InteractAgent(agent_id)
                since_reissue = 0

            player_distance = Utils.Distance(Player.GetXY(), Agent.GetXY(agent_id))
            if player_distance > 220.0:
                yield from Routines.Yield.Movement.FollowPath(
                    [crafter.GetDisplayPosition()],
                    tolerance=150,
                    timeout=5000,
                    log=False,
                )
            else:
                yield from Routines.Yield.wait(retry_interval)

            elapsed += retry_interval
            since_reissue += retry_interval

        return crafter._service_window_is_open()

    def collect_crafter_data_with_retries(self, crafter: Any, max_attempts: int = 3, retry_wait_ms: int = 500):
        collected_any = False

        for attempt in range(1, max_attempts + 1):
            if self.state.stop_requested:
                return False

            collected = crafter.CollectData()
            collected_any = collected_any or collected

            if not crafter.last_collection_had_pending_names:
                return collected_any

            if attempt < max_attempts:
                PySystem.Console.Log(
                    self.module_name,
                    f"Retrying '{crafter.name}' collection because some item names are not ready yet ({attempt}/{max_attempts - 1}).",
                    PySystem.Console.MessageType.Info,
                )
                yield from Routines.Yield.wait(retry_wait_ms)

        return collected_any


CRAFTER_SWEEP_CONTROLLER = CrafterSweepController()
