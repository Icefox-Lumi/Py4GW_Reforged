#region FSM

import PySystem
import traceback
from collections.abc import Iterator
from typing import Any
from typing import Callable
from typing import Optional
from typing import Protocol
from typing import cast
from weakref import ReferenceType
from weakref import ref

from .Timer import Timer, ThrottledTimer
from .Console import ConsoleLog, Console


class _DispatchReceipt(Protocol):
    _fsm_dispatch_receipt: bool

    def _attach_fsm(self, owner: "_FSMDispatchOwner", run: object, attachment: object) -> bool: ...
    def _detach_fsm(self, owner: "_FSMDispatchOwner", run: object, attachment: object) -> None: ...
    def _advance_fsm(self, owner: "_FSMDispatchOwner", run: object, attachment: object) -> bool: ...
    def _discard_factory_result(self) -> None: ...


class _FSMDispatchOwner(Protocol):
    _control_token: int
    _dispatch_run_token: object | None
    current_state: "FSM.State | None"
    managed_coroutines: list[Any]
    _managed_dispatch_bindings: dict[int, tuple[_DispatchReceipt, object, object]]

    def _add_managed(self, gen: Any) -> bool: ...
    def _detach_dispatch_binding(self, binding: tuple[_DispatchReceipt, object, object]) -> bool: ...
    def _dispatch_binding_is_current(self, receipt: _DispatchReceipt, run: object, attachment: object) -> bool: ...
    def _discard_factory_result(self, routine: Any) -> None: ...


class _StateIdentity(Protocol):
    _activation_token: int
    _owner_ref: ReferenceType[_FSMDispatchOwner] | None


class _SelfManagedIdentity(Protocol):
    _coroutine_binding: tuple[_DispatchReceipt, object, object] | None


class FSM:

    def __init__(self, name: str, log_actions: bool = False):
        """
        Initialize the FSM with a name and track its states and transitions.
        :param name: The name of the FSM (for logging and identification purposes).
        """
        self.name: str = name  # Store the FSM name
        self.states: list[FSM.State] = []  # List to store all states in order
        self.current_state: FSM.State | None = None  # Track the current state
        self.state_counter = 0  # Internal counter for state IDs
        self.log_actions = log_actions  # Whether to log state transitions and actions
        self.finished = False  # Track whether the FSM has completed all states
        self.paused = False
        self.on_transition: Callable[[str, str], Any] | None = None
        self.on_complete: Callable[[], Any] | None = None
        self.managed_coroutines: list[Any] = []  # already added for self-managed coroutines
        self._named_managed: dict[str, Any] = {}  # key -> generator instance
        self.delay_timer = ThrottledTimer()
        self._dispatch_run_token: object | None = None
        self._control_token: int = 0
        self._managed_dispatch_bindings: dict[int, tuple[_DispatchReceipt, object, object]] = {}
        self._named_managed_attempts: dict[str, object] = {}
        self._active_update_claims: list[tuple[Any, ...]] = []
        self._transition_claim: tuple[Any, ...] | None = None

    def _begin_control(self) -> int:
        self._control_token += 1
        return self._control_token

    def _capture_control(self) -> tuple[int, object | None, "FSM.State | None", int | None]:
        state = self.current_state
        return (
            self._control_token,
            self._dispatch_run_token,
            state,
            cast(int, getattr(state, "_activation_token")) if state is not None else None,
        )

    def _control_is_current(self, captured: tuple[int, object | None, "FSM.State | None", int | None]) -> bool:
        control, run, state, activation = captured
        return (
            self._control_token == control
            and self._dispatch_run_token is run
            and self.current_state is state
            and (state is None or cast(int, getattr(state, "_activation_token")) == activation)
        )

    def _expire_dispatch_run(self) -> None:
        self._dispatch_run_token = None
        bindings = tuple(self._managed_dispatch_bindings.values())
        self._managed_dispatch_bindings.clear()
        self._named_managed_attempts.clear()
        for receipt, run, attachment in bindings:
            cast(Callable[[_FSMDispatchOwner, object, object], None], getattr(receipt, "_detach_fsm"))(
                self, run, attachment
            )

    def _bind_state(self, state: "FSM.State") -> None:
        setattr(state, "_owner_ref", ref(self))

    def _checked_reset_enter(self, state: "FSM.State", control: int, run: object | None) -> bool:
        identity = cast(_StateIdentity, state)
        activation = cast(int, getattr(identity, "_activation_token"))
        state.reset()
        if self._control_token != control or self._dispatch_run_token is not run or self.current_state is not state:
            return False
        if (
            type(state) in (FSM.State, FSM.ConditionState, FSM.YieldRoutineState, FSM.SelfManagedYieldState)
            and cast(int, getattr(identity, "_activation_token")) != activation + 1
        ):
            return False
        captured = self._capture_control()
        state.enter()
        return self._control_is_current(captured)

    def _claim_update(self, kind: str) -> tuple[Any, ...] | None:
        captured = self._capture_control()
        if self._transition_claim is not None and self._transition_claim[0] == captured:
            return None
        if any(
            claim[1] == captured and (kind == "run_until" or claim[0] == "update")
            for claim in self._active_update_claims
        ):
            return None
        claim = (kind, captured, object())
        self._active_update_claims.append(claim)
        return claim

    def _release_update(self, claim: tuple[Any, ...]) -> None:
        self._active_update_claims[:] = [item for item in self._active_update_claims if item is not claim]

    def _claim_transition(self) -> tuple[Any, ...] | None:
        captured = self._capture_control()
        if self._transition_claim is not None and self._transition_claim[0] == captured:
            return None
        claim = (captured, object())
        self._transition_claim = claim
        return claim

    def _release_transition(self, claim: tuple[Any, ...]) -> None:
        if self._transition_claim is claim:
            self._transition_claim = None

    def _dispatch_binding_is_current(self, receipt: _DispatchReceipt, run: object, attachment: object) -> bool:
        binding = self._managed_dispatch_bindings.get(id(receipt))
        return (
            binding is not None
            and binding[0] is receipt
            and binding[1] is run
            and binding[2] is attachment
            and self._dispatch_run_token is run
            and not self.finished
            and self.current_state is not None
            and any(item is receipt for item in self.managed_coroutines)
        )

    def _detach_dispatch_binding(self, binding: tuple[_DispatchReceipt, object, object]) -> bool:
        receipt, run, attachment = binding
        if self._managed_dispatch_bindings.get(id(receipt)) is not binding:
            return False
        del self._managed_dispatch_bindings[id(receipt)]
        for index, item in enumerate(self.managed_coroutines):
            if item is receipt:
                del self.managed_coroutines[index]
                break
        cast(Callable[[_FSMDispatchOwner, object, object], None], getattr(receipt, "_detach_fsm"))(
            self, run, attachment
        )
        return True

    def _discard_factory_result(self, routine: Any) -> None:
        if getattr(routine, "_fsm_dispatch_receipt", False):
            cast(Callable[[], None], getattr(routine, "_discard_factory_result"))()
    
    #region State
    class State:
        def __init__(
            self,
            id,
            name=None,
            execute_fn=None,
            exit_condition=None,
            transition_delay_ms=0,
            run_once=True,
            on_enter=None,
            on_exit=None,
        ):
            """
            :param id: Internal ID of the state.
            :param name: Optional name of the state (for debugging purposes).
            :param execute_fn: A function representing the block of code to be executed in this state.
            :param exit_condition: A function that returns True/False to determine if it can transition to the next state.
            :param run_once: Whether the execution function should run only once (default: True).
            :param transition_delay_ms: Delay in milliseconds before checking the exit condition (default: 0).
            """
            self.id: int = id
            self.name: str = name or f"State-{id}"  # If no name is provided, use "State-ID"
            self.execute_fn: Callable[[], Any] = execute_fn or (lambda: None)  # Default to no action if not provided
            self.exit_condition: Callable[[], bool] = exit_condition or (
                lambda: True
            )  # Default to False if not provided
            self.run_once = run_once  # Flag to control whether the action runs once or repeatedly
            self.executed = False  # Track whether the state's execute function has been run
            self.transition_delay_ms = transition_delay_ms  # Delay before transitioning to the next state
            self.transition_timer = Timer()  # Timer to manage the delay
            self.on_enter: Callable[[], Any] = on_enter or (lambda: None)
            self.on_exit: Callable[[], Any] = on_exit or (lambda: None)
            self.next_state: FSM.State | None = None
            self.event_transitions: dict[str, str] = {}
            self._owner_ref: ReferenceType[_FSMDispatchOwner] | None = None
            self._activation_token: int = 0
            self._invocation_token: tuple[Any, ...] | None = None

        def _capture_context(self) -> tuple[_FSMDispatchOwner | None, int, object | None, int, "FSM.State | None"]:
            owner = self._owner_ref() if self._owner_ref is not None else None
            return (
                owner,
                cast(int, getattr(owner, "_control_token")) if owner is not None else 0,
                cast(object | None, getattr(owner, "_dispatch_run_token")) if owner is not None else None,
                self._activation_token,
                owner.current_state if owner is not None else None,
            )

        def _context_is_current(
            self, captured: tuple[_FSMDispatchOwner | None, int, object | None, int, "FSM.State | None"]
        ) -> bool:
            owner, control, run, activation, current_state = captured
            return self._activation_token == activation and (
                owner is None
                or (
                    cast(int, getattr(owner, "_control_token")) == control
                    and getattr(owner, "_dispatch_run_token") is run
                    and owner.current_state is current_state
                )
            )

        def _begin_invocation(self) -> tuple[Any, ...] | None:
            captured = self._capture_context()
            if self._invocation_token is not None and self._invocation_token[0] == captured:
                return None
            claim = (captured, object())
            self._invocation_token = claim
            return claim

        def _invocation_is_current(self, claim: tuple[Any, ...]) -> bool:
            return self._invocation_token is claim and self._context_is_current(claim[0])

        def _release_invocation(self, claim: tuple[Any, ...]) -> None:
            if self._invocation_token is claim:
                self._invocation_token = None

        def enter(self):
            self.on_enter()

        def exit(self):
            self.on_exit()

        def reset_transition_timer(self):
            self.transition_timer.Reset()

        def execute(self):
            """Run the state's block of code. If `run_once` is True, run it only once."""
            claim = self._begin_invocation()
            if claim is None:
                return
            try:
                if not self.run_once or not self.executed:
                    self.execute_fn()
                    if not self._invocation_is_current(claim):
                        return
                    if not self.executed:  # Only reset timer on first execution
                        self.reset_transition_timer()
                    self.executed = True
            finally:
                self._release_invocation(claim)

        def can_exit(self):
            """
            Check if the exit condition is met and if the transition delay has passed.
            """
            if not self.transition_timer.HasElapsed(self.transition_delay_ms):
                return False
            
            return self.exit_condition()
            
        def reset(self):
            """Reset the state so it can be re-entered, if needed."""
            self._activation_token += 1
            self._invocation_token = None
            self.executed = False
            self.transition_timer.Stop()  # Reset timer when resetting the state

        def set_next_state(self, next_state):
            """Set the next state for transitions."""
            self.next_state = next_state
        
        def add_event_transition(self, event_name: str, target_state_name: str):
            """
            Define a transition triggered by a specific event.

            :param event_name: The name of the event that triggers this transition.
            :param target_state_name: The name of the state to transition to.
            """
            if not isinstance(event_name, str) or not isinstance(target_state_name, str):
                raise TypeError("Event name and target state name must be strings.")
            self.event_transitions[event_name] = target_state_name
     
    #region ConditionState  
    class ConditionState(State):
        def __init__(self, id, name=None, condition_fn=None, sub_fsm=None,
                 on_enter=None, on_exit=None, log_actions=False):
            """
            A state that evaluates a condition and decides whether to continue or run a sub-FSM.

            :param condition_fn: Function that returns True/False. If True,
                                 it runs the sub_fsm and waits for it to finish before transitioning.
            :param sub_fsm: An optional sub-FSM that will be run if condition_fn returns False.
            """
            super().__init__(id, name, on_enter=on_enter, on_exit=on_exit)
            self.condition_fn = condition_fn or (lambda: True)  # Default to True if no condition provided
            self.sub_fsm = sub_fsm
            self.sub_fsm_active = False
            self.log_actions = log_actions

        def execute(self):
            """
            Execute the condition function. If it returns False, mark the state as completed.
            If it returns True, start the subroutine FSM (if provided).
            """
            claim = self._begin_invocation()
            if claim is None:
                return
            try:
                sub_fsm = cast("FSM | None", self.sub_fsm)
                if self.sub_fsm_active:
                    if sub_fsm and not sub_fsm.is_finished():
                        sub_fsm.update()
                        return
                    self.sub_fsm_active = False
                    self.executed = True
                    self.reset_transition_timer()
                    return

                condition = cast(Callable[[], bool], self.condition_fn)()
                if not self._invocation_is_current(claim):
                    return
                if not condition:
                    self.executed = True
                    self.reset_transition_timer()
                    return

                if sub_fsm and not self.sub_fsm_active:
                    if self.log_actions:
                        ConsoleLog("FSM", f"Starting FSM Subroutine", Console.MessageType.Success)
                    child_identity = cast(_FSMDispatchOwner, sub_fsm)
                    child_control = cast(int, getattr(child_identity, "_control_token"))
                    sub_fsm.reset()
                    if (
                        not self._invocation_is_current(claim)
                        or cast(int, getattr(child_identity, "_control_token")) != child_control + 1
                    ):
                        return
                    sub_fsm.start()
                    if (
                        not self._invocation_is_current(claim)
                        or cast(int, getattr(child_identity, "_control_token")) != child_control + 2
                    ):
                        return
                    self.sub_fsm_active = True
                else:
                    self.executed = True
                    self.reset_transition_timer()
            finally:
                self._release_invocation(claim)
            
        def can_exit(self):
            """
            The node can exit only if the condition is met or the sub-FSM has finished running.
            """
            return self.executed and not self.sub_fsm_active
        
        def reset(self):
            super().reset()
            self.sub_fsm_active = False
            if self.sub_fsm:
                self.sub_fsm.reset()
      
    #region YieldRoutineState  
    class YieldRoutineState(State):
        def __init__(self, id, name=None, coroutine_fn=None):
            """
            A state that runs a yield-based coroutine and waits for it to complete.

            :param coroutine_fn: A function that returns a generator (yield-based coroutine)
            """
            super().__init__(id=id, name=name or f"YieldRoutine-{id}")
            self.coroutine_fn = coroutine_fn
            self.coroutine_instance = None

        def execute(self):
            from Py4GWCoreLib import GLOBAL_CACHE

            claim = self._begin_invocation()
            if claim is None:
                return
            try:
                if not self.executed:
                    if self.coroutine_fn:
                        try:
                            routine = cast(Callable[[], Any], self.coroutine_fn)()
                            if getattr(routine, "_fsm_dispatch_receipt", False):
                                # This state cannot supply an FSM attachment to a global scheduler.
                                cast(Callable[[], None], getattr(routine, "_discard_factory_result"))()
                                raise TypeError("Dispatch receipts require an FSM-managed coroutine attachment")
                            elif self._invocation_is_current(claim):
                                self.coroutine_instance: Any = routine
                                if routine:
                                    GLOBAL_CACHE.Coroutines.append(routine)
                        except Exception as e:
                            ConsoleLog(
                                "FSM",
                                f"Error starting coroutine for state '{self.name}': {e}",
                                Console.MessageType.Error,
                            )
                    if not self._invocation_is_current(claim):
                        return
                    self.reset_transition_timer()
                    self.executed = True
            finally:
                self._release_invocation(claim)

        def can_exit(self):
            from Py4GWCoreLib import GLOBAL_CACHE
            """
            Exit only if coroutine is finished.
            """
            if not self.transition_timer.HasElapsed(self.transition_delay_ms):
                return False

            # Check if coroutine is no longer running
            if self.coroutine_instance and self.coroutine_instance in GLOBAL_CACHE.Coroutines:
                return False  # Still running

            return True
        
        def reset(self):
            super().reset()
            from Py4GWCoreLib import GLOBAL_CACHE

            routine = self.coroutine_instance
            self.coroutine_instance = None
            if routine and routine in GLOBAL_CACHE.Coroutines:
                try:
                    GLOBAL_CACHE.Coroutines.remove(routine)
                except ValueError:
                    pass
  
    #region SelfManagedYieldState
    class SelfManagedYieldState(State):
        def __init__(self, id: int, fsm: "FSM", name: str | None = None, coroutine_fn: Callable[[], Any] | None = None):
            super().__init__(id=id, name=name or f"SelfYield-{id}")
            self._fsm: _FSMDispatchOwner = fsm
            self.coroutine_fn: Callable[[], Any] | None = coroutine_fn
            self.coroutine_instance: Any = None
            self._coroutine_binding: tuple[_DispatchReceipt, object, object] | None = None

        def execute(self):
            # Exactly like YieldRoutineState's start, but register into FSM list (not GLOBAL_CACHE)
            claim = self._begin_invocation()
            if claim is None:
                return
            try:
                if not self.executed:
                    if self.coroutine_fn:
                        try:
                            routine = self.coroutine_fn()
                            if not self._invocation_is_current(claim):
                                cast(Callable[[Any], None], getattr(self._fsm, "_discard_factory_result"))(routine)
                                return
                            if getattr(routine, "_fsm_dispatch_receipt", False):
                                try:
                                    attached = cast(Callable[[Any], bool], getattr(self._fsm, "_add_managed"))(routine)
                                except Exception:
                                    cast(Callable[[Any], None], getattr(self._fsm, "_discard_factory_result"))(routine)
                                    raise
                                bindings = cast(
                                    dict[int, tuple[_DispatchReceipt, object, object]],
                                    getattr(self._fsm, "_managed_dispatch_bindings"),
                                )
                                binding = bindings.get(id(routine))
                                if not self._invocation_is_current(claim):
                                    if attached and binding is not None:
                                        cast(
                                            Callable[[tuple[_DispatchReceipt, object, object]], bool],
                                            getattr(self._fsm, "_detach_dispatch_binding"),
                                        )(binding)
                                    cast(Callable[[Any], None], getattr(self._fsm, "_discard_factory_result"))(routine)
                                    return
                                if (
                                    attached
                                    and binding is not None
                                    and cast(
                                        Callable[[_DispatchReceipt, object, object], bool],
                                        getattr(self._fsm, "_dispatch_binding_is_current"),
                                    )(*binding)
                                ):
                                    self.coroutine_instance = routine
                                    self._coroutine_binding = binding
                                else:
                                    cast(Callable[[Any], None], getattr(self._fsm, "_discard_factory_result"))(routine)
                            else:
                                self.coroutine_instance = routine
                                if routine:
                                    self._fsm.managed_coroutines.append(routine)
                        except Exception as e:
                            ConsoleLog(
                                "FSM",
                                f"Error starting self-managed coroutine for state '{self.name}': {e}",
                                Console.MessageType.Error,
                            )
                    if not self._invocation_is_current(claim):
                        return
                    self.reset_transition_timer()
                    self.executed = True
            finally:
                self._release_invocation(claim)

        def can_exit(self):
            # Wait until the coroutine finishes (i.e., is no longer in the FSM list),
            # and the transition delay (if any) has elapsed.
            if not self.transition_timer.HasElapsed(self.transition_delay_ms):
                return False
            if self._coroutine_binding is not None:
                return not cast(
                    Callable[[_DispatchReceipt, object, object], bool],
                    getattr(self._fsm, "_dispatch_binding_is_current"),
                )(*self._coroutine_binding)
            if self.coroutine_instance and self.coroutine_instance in self._fsm.managed_coroutines:
                return False
            return True

        def reset(self):
            super().reset()
            # If we jump back or reset while the gen is still tracked, detach it
            routine = self.coroutine_instance
            binding = self._coroutine_binding
            self.coroutine_instance = None
            self._coroutine_binding = None
            if binding is not None:
                cast(
                    Callable[[tuple[_DispatchReceipt, object, object]], bool],
                    getattr(self._fsm, "_detach_dispatch_binding"),
                )(binding)
            elif routine and routine in self._fsm.managed_coroutines:
                try:
                    self._fsm.managed_coroutines.remove(routine)
                except ValueError:
                    pass

        
    #region FSM Methods 
    def SetLogBehavior(self, log_actions=False):
        """
        Set whether to log state transitions and actions.
        :param log_actions: Whether to log state transitions and actions (default: False).
        """
        self.log_actions = log_actions

    def GetLogBehavior(self):
        """Get the current logging behavior setting."""
        return self.log_actions

    def AddState(
        self,
        name=None,
        execute_fn=None,
        exit_condition=None,
        transition_delay_ms=0,
        run_once=True,
        on_enter=None,
        on_exit=None,
    ):
        """Add a state with an optional name, execution function, and exit condition."""
        state = FSM.State(
            id=self.state_counter,
            name=name,
            execute_fn=execute_fn,
            exit_condition=exit_condition,
            run_once=run_once,
            transition_delay_ms=transition_delay_ms,
            on_enter=on_enter,
            on_exit=on_exit,
        )
        self._bind_state(state)

        if self.states:
            self.states[-1].set_next_state(state)

        self.states.append(state)
        self.state_counter += 1
        
    def AddYieldRoutineStep(self, name, coroutine_fn, transition_delay_ms=0):
        """
        Add a yield-based coroutine step to the FSM.
        The coroutine is added to GLOBAL_CACHE.Coroutines and the FSM waits until it finishes.

        :param name: Name of the state.
        :param coroutine_fn: Function that returns a yield-based generator.
        """
        step = self.YieldRoutineState(id=self.state_counter, name=name, coroutine_fn=coroutine_fn)
        self._bind_state(step)
        step.transition_delay_ms = transition_delay_ms
        if self.states:
            self.states[-1].set_next_state(step)
        self.states.append(step)
        self.state_counter += 1

    def AddSelfManagedYieldStep(self, name, coroutine_fn, transition_delay_ms=0):
        step = FSM.SelfManagedYieldState(id=self.state_counter, fsm=self, name=name, coroutine_fn=coroutine_fn)
        self._bind_state(step)
        step.transition_delay_ms = transition_delay_ms
        if self.states:
            self.states[-1].set_next_state(step)
        self.states.append(step)
        self.state_counter += 1



    def AddSubroutine(self, name=None, condition_fn=None, sub_fsm=None, on_enter=None, on_exit=None):
        """Add a condition node that evaluates a condition and can run a subroutine FSM."""
        condition_node = FSM.ConditionState(
            id=self.state_counter,
            name=name,
            condition_fn=condition_fn,
            sub_fsm=sub_fsm,
            on_enter=on_enter,
            on_exit=on_exit,
            log_actions=self.log_actions,
        )
        self._bind_state(condition_node)
        if self.states:
            self.states[-1].set_next_state(condition_node)
        self.states.append(condition_node)
        self.state_counter += 1
            
    def _cleanup_coroutines(self):
        """Detach any generators this FSM started, to avoid duplicates on start/reset/stop."""
        # Keep generator finalizers outside the cleanup writes; they can restart the FSM.
        _retained = tuple(self.managed_coroutines) + tuple(
            state.coroutine_instance for state in self.states if isinstance(state, FSM.SelfManagedYieldState)
        )
        self._expire_dispatch_run()
        # clear the central list
        self.managed_coroutines.clear()
        # clear per-state handles (SelfManagedYieldState only)
        for s in self.states:
            if hasattr(FSM, "SelfManagedYieldState") and isinstance(s, FSM.SelfManagedYieldState):
                s.coroutine_instance = None
                setattr(cast(_SelfManagedIdentity, s), "_coroutine_binding", None)


    def start(self):
        """Start the FSM by setting the initial state."""
        if not self.states:
            raise ValueError(f"{self.name}: No states have been added to the FSM.")
        control = self._begin_control()
        self._cleanup_coroutines()
        if self._control_token != control:
            return
        self.current_state = self.states[0]
        self.finished = False
        self._dispatch_run_token = object()
        ConsoleLog(
            "FSM",
            f"{self.name}: Starting FSM with initial state: {self.current_state.name}",
            Console.MessageType.Success,
        )

    def stop(self):
        """Stop the FSM and mark it as finished."""
        control = self._begin_control()
        self._cleanup_coroutines()
        if self._control_token != control:
            return
        self.current_state = None
        self.finished = True

        if self.log_actions:
            ConsoleLog("FSM", f"{self.name}: FSM has been stopped by user.", Console.MessageType.Info)

    def reset(self):
        """Reset the FSM to the initial state without starting it."""
        if not self.states:
            raise ValueError(f"{self.name}: No states have been added to the FSM.")
        control = self._begin_control()
        self._cleanup_coroutines()
        if self._control_token != control:
            return
        self.current_state = self.states[0]  # Reset to the first state
        self.finished = False
        run = object()
        self._dispatch_run_token = run
        for state in self.states:
            identity = cast(_StateIdentity, state)
            activation = cast(int, getattr(identity, "_activation_token"))
            state.reset()  # Reset all states
            if self._control_token != control or self._dispatch_run_token is not run:
                return
            if (
                type(state) in (FSM.State, FSM.ConditionState, FSM.YieldRoutineState, FSM.SelfManagedYieldState)
                and cast(int, getattr(identity, "_activation_token")) != activation + 1
            ):
                # Composite reset/start callers must observe this activation-only abort.
                self._begin_control()
                return

        if self.log_actions:
            ConsoleLog("FSM", f"{self.name}: FSM has been reset.", Console.MessageType.Info)
            
    def ResetAndStartAtStep(self, state_name: str):
        """
        Fully reset the FSM, clear all managed coroutines, and jump directly to the specified step.

        This is especially useful for recovery situations (e.g. party wipe) where
        the FSM must restart cleanly but resume execution at a specific entry point.
        """
        if not self.states:
            raise ValueError(f"{self.name}: No states have been added to the FSM.")
        control = self._begin_control()
        self._expire_dispatch_run()

        # --- Step 1: Clean up all coroutine and state references ---
        # self._cleanup_coroutines()
        # for state in self.states:
        #    state.reset()

        # --- Step 2: Reset finished/paused flags ---
        self.finished = False
        self.paused = False

        # --- Step 3: Find and jump to the desired state ---
        target_state = None
        for s in self.states:
            if s.name == state_name:
                target_state = s
                break

        if not target_state:
            raise ValueError(f"{self.name}: State '{state_name}' not found.")

        self.current_state = target_state
        run = object()
        self._dispatch_run_token = run
        if not self._checked_reset_enter(target_state, control, run):
            return

        # --- Step 4: Logging and resume ---
        if self.log_actions:
            ConsoleLog("FSM", f"{self.name}: Reset and started at step '{state_name}'", Console.MessageType.Success)

        # Ensure FSM resumes execution after being paused
        self.paused = False


    def get_state_names(self):
        return [s.name for s in self.states]

    def terminate(self):
        self._begin_control()
        self._expire_dispatch_run()
        if self.log_actions:
            ConsoleLog("FSM", f"{self.name}: Terminated forcefully.", Console.MessageType.Warning)
        self.current_state = None
        self.finished = True

    def run_until(self, condition_fn: Callable[[], bool]):
        claim = self._claim_update("run_until")
        if claim is None:
            return
        try:
            while not self.finished:
                captured = self._capture_control()
                done = condition_fn()
                if not self._control_is_current(captured) or done:
                    return
                self.update()
                if self._dispatch_run_token is not captured[1]:
                    return
        finally:
            self._release_update(claim)
    
    def set_completion_callback(self, callback_fn):
        self.on_complete = callback_fn
    
    def get_current_state_index(self):
        if not self.current_state or self.current_state not in self.states:
            return -1
        return self.states.index(self.current_state)

    def get_next_state_index(self):
        if not self.current_state:
            return -1
        next_state = getattr(self.current_state, 'next_state', None)
        if not next_state or next_state not in self.states:
            return -1
        return self.states.index(next_state)

    def interrupt(self, fn):
        if not self.current_state:
            return
        state = self.current_state
        original_exit = state.exit

        def wrapped_exit():
            captured = self._capture_control()
            original_exit()
            if self._control_is_current(captured) and self.current_state is state:
                fn()

        state.exit = wrapped_exit
    
    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def is_paused(self):
        return self.paused

    def set_transition_callback(self, callback_fn):
        self.on_transition = callback_fn

    def has_state(self, name):
        return any(s.name == name for s in self.states)

    def restart(self):
        control = self._control_token
        self.reset()
        if self._control_token == control + 1:
            self.start()

    def AddWaitState(
        self,
        name: str,
        condition_fn: Callable[[], bool],
        timeout_ms: int = 10000,
        on_timeout: Callable[[], Any] | None = None,
        on_enter: Callable[[], Any] | None = None,
        on_exit: Callable[[], Any] | None = None,
    ):
        timer = Timer()

        def exit_fn():
            captured = self._capture_control()
            condition = condition_fn()
            if not self._control_is_current(captured):
                return False
            if condition:
                return True
            if timer.HasElapsed(timeout_ms):
                if on_timeout:
                    try:
                        on_timeout()
                    except Exception as e:
                        if self.log_actions:
                            ConsoleLog(
                                "FSM",
                                f"Error in on_timeout for state '{name}': {e}",
                                PySystem.Console.MessageType.Error,
                            )
                return True
            return False

        wait_state = FSM.State(
            id=self.state_counter,
            name=name,
            execute_fn=lambda: None,
            exit_condition=exit_fn,
            run_once=True,
            on_enter=on_enter,  # <-- PASS on_enter
            on_exit=on_exit,
        )
        wait_state.transition_timer = timer
        self._bind_state(wait_state)
        if self.states:
            self.states[-1].set_next_state(wait_state)

        self.states.append(wait_state)
        self.state_counter += 1

    def trigger_event(self, event_name: str) -> bool:
        """
        Triggers an event, potentially causing an immediate state transition
        if the current state is configured to handle it.

        :param event_name: The name of the event to trigger.
        :return: True if the event caused a transition, False otherwise.
        """
        if self.paused or self.finished or not self.current_state:
            return False  # Cannot transition if paused, finished, or not started

        source_state = self.current_state
        captured = self._capture_control()
        target_state_name = source_state.event_transitions.get(event_name)

        if target_state_name:
            target_state = self._get_state_by_name(target_state_name)
            if target_state:
                if self.log_actions:
                    ConsoleLog(
                        "FSM",
                        f"{self.name}: Event '{event_name}' triggered transition from '{self.current_state.name}' to '{target_state.name}'",
                        PySystem.Console.MessageType.Info,
                    )

                claim = self._claim_transition()
                if claim is None:
                    return False
                try:
                    original_state_name = source_state.name
                    source_state.exit()
                    if not self._control_is_current(captured):
                        return False
                    if self.on_transition:
                        try:
                            self.on_transition(original_state_name, target_state.name)
                        except Exception as e:
                            ConsoleLog(
                                "FSM",
                                f"Error in on_transition callback during event '{event_name}': {e}",
                                PySystem.Console.MessageType.Error,
                            )
                        if not self._control_is_current(captured):
                            return False

                    control = self._begin_control()
                    self.current_state = target_state
                    return self._checked_reset_enter(target_state, control, captured[1])
                finally:
                    self._release_transition(claim)
            else:
                # Log error: target state name defined but not found
                ConsoleLog(
                    "FSM",
                    f"{self.name}: Event '{event_name}' defined transition to unknown state '{target_state_name}' from state '{self.current_state.name}'",
                    PySystem.Console.MessageType.Error,
                )
                return False
        else:
            # Event not handled by the current state
            if self.log_actions:
                ConsoleLog(
                    "FSM",
                    f"{self.name}: Event '{event_name}' triggered but not handled by current state '{self.current_state.name}'",
                    PySystem.Console.MessageType.Debug,
                )
            return False

    def update(self):

        if not self.current_state:
            if self.log_actions:
                ConsoleLog("FSM", f"{self.name}: FSM has not been started.", PySystem.Console.MessageType.Warning)
            return

        if self.finished:
            if self.log_actions:
                ConsoleLog("FSM", f"{self.name}: FSM has finished.", PySystem.Console.MessageType.Warning)
            return

        update_claim = self._claim_update("update")
        if update_claim is None:
            return
        captured = self._capture_control()
        try:
            # Capture attachments with the list, before any routine can replace them.
            scheduled = [
                (routine, self._managed_dispatch_bindings.get(id(routine))) for routine in self.managed_coroutines[:]
            ]
            for routine, binding in scheduled:
                participating = getattr(routine, "_fsm_dispatch_receipt", False)
                try:
                    if participating:
                        if binding is None or not self._dispatch_binding_is_current(*binding):
                            continue
                        if not cast(
                            Callable[[_FSMDispatchOwner, object, object], bool], getattr(binding[0], "_advance_fsm")
                        )(self, binding[1], binding[2]):
                            self._detach_dispatch_binding(binding)
                    else:
                        next(routine)
                except StopIteration:
                    if participating:
                        if binding is not None:
                            self._detach_dispatch_binding(binding)
                    else:
                        try:
                            self.managed_coroutines.remove(routine)
                        except ValueError:
                            pass
                except Exception as e:
                    state_name = self.current_state.name if self.current_state else "Unknown"
                    tb = traceback.format_exc()
                    ConsoleLog(
                        "FSM",
                        f"Error in self-managed coroutine at state '{state_name}': {e}\nTraceback:\n{tb}",
                        Console.MessageType.Error,
                    )
                    if participating:
                        if binding is not None:
                            self._detach_dispatch_binding(binding)
                    else:
                        try:
                            self.managed_coroutines.remove(routine)
                        except ValueError:
                            pass

            if not self._control_is_current(captured):
                return
            if self.paused:
                if self.log_actions:
                    ConsoleLog("FSM", f"{self.name}: FSM is paused.", PySystem.Console.MessageType.Warning)
                return

            current_state = self.current_state
            if self.log_actions:
                ConsoleLog(
                    "FSM", f"{self.name}: Executing state: {current_state.name}", PySystem.Console.MessageType.Info
                )
            current_state.execute()
            if not self._control_is_current(captured):
                return
            can_exit = current_state.can_exit()
            if not self._control_is_current(captured) or not can_exit:
                return

            transition_claim = self._claim_transition()
            if transition_claim is None:
                return
            try:
                current_state.exit()
                if not self._control_is_current(captured):
                    return
                next_state_polling = getattr(current_state, 'next_state', None)
                if next_state_polling:
                    original_state_name = current_state.name
                    if self.on_transition:
                        try:
                            self.on_transition(original_state_name, next_state_polling.name)
                        except Exception as e:
                            ConsoleLog(
                                "FSM",
                                f"Error in on_transition callback during polling transition: {e}",
                                PySystem.Console.MessageType.Error,
                            )
                        if not self._control_is_current(captured):
                            return

                    control = self._begin_control()
                    self.current_state = next_state_polling
                    if not self._checked_reset_enter(next_state_polling, control, captured[1]):
                        return
                    if self.log_actions:
                        ConsoleLog(
                            "FSM",
                            f"{self.name}: Transitioning to state: {next_state_polling.name}",
                            PySystem.Console.MessageType.Info,
                        )
                    return

                final_state_name = current_state.name
                self._begin_control()
                self._expire_dispatch_run()
                self.current_state = None
                self.finished = True
                if self.log_actions:
                    ConsoleLog(
                        "FSM",
                        f"{self.name}: Reached the final state: {final_state_name}. FSM has completed.",
                        PySystem.Console.MessageType.Success,
                    )
                if self.on_complete:
                    try:
                        self.on_complete()
                    except Exception as e:
                        ConsoleLog("FSM", f"Error in on_complete callback: {e}", PySystem.Console.MessageType.Error)
            finally:
                self._release_transition(transition_claim)
        finally:
            self._release_update(update_claim)

    def is_started(self):
        """Check whether the FSM has been started."""
        return self.current_state is not None and not self.finished
                
    def is_finished(self):
        """Check whether the FSM has finished executing all states."""
        return self.finished

    def jump_to_state_by_name(self, state_name):
        """Jump to a specific state by its name."""
        for state in self.states:
            if state.name == state_name:
                control = self._begin_control()
                self.current_state = state
                if self._dispatch_run_token is None and not self.finished:
                    self._dispatch_run_token = object()
                if not self._checked_reset_enter(state, control, self._dispatch_run_token):
                    return
                if self.log_actions:
                    PySystem.Console.Log(
                        "FSM",
                        f"{self.name}: Jumped to state: {self.current_state.name}",
                        PySystem.Console.MessageType.Info,
                    )
                return
        raise ValueError(f"State with name '{state_name}' not found.")
    
    def jump_to_state_by_step_number(self, index: int):
        """Jump to a specific state by its index (0-based)."""
        if 0 <= index < len(self.states):
            state = self.states[index]
            control = self._begin_control()
            self.current_state = state
            if self._dispatch_run_token is None and not self.finished:
                self._dispatch_run_token = object()
            if not self._checked_reset_enter(state, control, self._dispatch_run_token):
                return
            if self.log_actions:
                PySystem.Console.Log(
                    "FSM", f"{self.name}: Jumped to state: {state.name}", PySystem.Console.MessageType.Info
                )
            return
        raise IndexError(f"State index '{index}' is out of range.")

    def get_current_state_number(self):
        """Get the current state number (index) in the FSM."""
        if self.current_state is None:
            return 0
        return self.states.index(self.current_state) + 1

    def get_state_count (self):
        """Get the total number of states in the FSM."""
        return len(self.states)

    def get_state_number_by_name(self, state_name):
        """Get the step number (index) by the state name."""
        for idx, state in enumerate(self.states):
            if state.name == state_name:
                return idx + 1
        return 0
    
    def get_state_name_by_number(self, state_number):
        """Get the state name by its number (index)."""
        if 1 <= state_number <= len(self.states):
            return self.states[state_number - 1].name
        return None

    def get_current_step_name(self):
        """Get the name of the current step (state) in the FSM."""
        if self.current_state is None:
            return f"{self.name}: FSM not started or finished"
        return self.current_state.name

    def get_next_step_name(self):
        """Get the name of the next step (state) in the FSM."""
        if self.current_state is None:
            return f"{self.name}: FSM not started or finished"
        if hasattr(self.current_state, 'next_state') and self.current_state.next_state:
            return self.current_state.next_state.name
        return f"{self.name}: No next state (final state reached)"

    def get_previous_step_name(self):
        """Get the name of the previous step (state) in the FSM."""
        if self.current_state is None:
            return f"{self.name}: FSM not started or finished"
        current_index = self.states.index(self.current_state)
        if current_index > 0:
            return self.states[current_index - 1].name
        return f"{self.name}: No previous state (first state)"
    
    def _get_state_by_name(self, state_name: str) -> Optional[State]:
        """Finds a state object by its name."""
        for state in self.states:
            if state.name == state_name:
                return state
        return None

    #Self managed external Coroutine handling
    # these coroutines are not scheduled in the FSM
    # we are managing their lifecycle manually
    # using the automatic yield of the FSM
    
    def _as_generator(self, obj):
        """Return a generator from obj (call if callable), or None on failure."""
        try:
            gen = obj() if callable(obj) else obj
            if gen is None:
                return None
            # rudimentary generator protocol check
            if hasattr(gen, "__next__") and hasattr(gen, "send"):
                return gen
        except Exception as e:
            ConsoleLog("FSM", f"{self.name}: Error creating generator: {e}", PySystem.Console.MessageType.Error)
        return None

    def _add_managed(self, gen: Any) -> bool:
        """Attach generator to FSM-managed list (no duplicates)."""
        if getattr(gen, "_fsm_dispatch_receipt", False):
            run = self._dispatch_run_token
            if run is None or self.finished or self.current_state is None:
                return False
            existing = self._managed_dispatch_bindings.get(id(gen))
            if existing is not None:
                if self._dispatch_binding_is_current(*existing):
                    return False
                self._detach_dispatch_binding(existing)
            for index, item in enumerate(self.managed_coroutines):
                if item is gen:
                    del self.managed_coroutines[index]
                    break
            captured = self._capture_control()
            receipt = cast(_DispatchReceipt, gen)
            binding = (receipt, run, object())
            self._managed_dispatch_bindings[id(gen)] = binding
            try:
                self.managed_coroutines.append(gen)
                accepted = cast(Callable[[_FSMDispatchOwner, object, object], bool], getattr(receipt, "_attach_fsm"))(
                    self, run, binding[2]
                )
                if accepted and self._control_is_current(captured) and self._dispatch_binding_is_current(*binding):
                    return True
            except Exception:
                self._detach_dispatch_binding(binding)
                raise
            self._detach_dispatch_binding(binding)
            return False
        if gen and gen not in self.managed_coroutines:
            self.managed_coroutines.append(gen)
            return True
        return False

    def _remove_managed(self, gen: Any) -> bool:
        """Detach generator from FSM-managed list."""
        if getattr(gen, "_fsm_dispatch_receipt", False):
            binding = self._managed_dispatch_bindings.get(id(gen))
            if binding is not None:
                return self._detach_dispatch_binding(binding)
            for index, item in enumerate(self.managed_coroutines):
                if item is gen:
                    del self.managed_coroutines[index]
                    return True
            return False
        try:
            self.managed_coroutines.remove(gen)
            return True
        except ValueError:
            return False

    def AddManagedCoroutine(self, name: str, routine_or_fn: Any) -> bool:
        """
        Attach a generator (or factory) under a required name.
        - No-ops if the same name is already attached and still managed.
        """
        # de-dupe by name
        existing = self._named_managed.get(name)
        if self.HasManagedCoroutine(name):
            return False  # already attached under this name
        attempt = object()
        self._named_managed_attempts[name] = attempt
        captured = self._capture_control()
        try:
            gen = cast(object | None, self._as_generator(routine_or_fn))
            if self._named_managed_attempts.get(name) is not attempt or not self._control_is_current(captured):
                self._discard_factory_result(gen)
                return False
            if not gen:
                return False
            if existing and self._named_managed.get(name) is existing:
                self._named_managed.pop(name, None)

            try:
                added = self._add_managed(gen)
            except Exception:
                self._discard_factory_result(gen)
                raise
            binding = self._managed_dispatch_bindings.get(id(gen))
            if self._named_managed_attempts.get(name) is not attempt or not self._control_is_current(captured):
                if added and binding is not None:
                    self._detach_dispatch_binding(binding)
                self._discard_factory_result(gen)
                return False
            if not added:
                self._discard_factory_result(gen)
                return False
            self._named_managed[name] = gen
            return True
        finally:
            if self._named_managed_attempts.get(name) is attempt:
                del self._named_managed_attempts[name]
    
    def AddManagedCoroutineStep(self, name: str, coroutine_fn, transition_delay_ms=0):
        """
        Add a state that will attach a managed coroutine at runtime.
        This allows coroutines to start only when the FSM reaches this step.
        """

        def _starter():
            self.AddManagedCoroutine(name, coroutine_fn)

        step = FSM.State(
            id=self.state_counter,
            name=name,
            execute_fn=_starter,
            exit_condition=lambda: True,  # move on immediately
            run_once=True,
        )
        self._bind_state(step)
        step.transition_delay_ms = transition_delay_ms

        if self.states:
            self.states[-1].set_next_state(step)

        self.states.append(step)
        self.state_counter += 1


    def RemoveManagedCoroutine(self, name: str) -> bool:
        """
        Detach the coroutine registered under 'name'.
        """
        self._named_managed_attempts.pop(name, None)
        gen = self._named_managed.pop(name, None)
        if not gen:
            return False
        return self._remove_managed(gen)
    
    def RemoveManagedCoroutineStep(self, name: str):
        """
        Add a state that will detach a managed coroutine at runtime.
        This allows coroutines to stop only when the FSM reaches this step.
        """

        def _stopper():
            self.RemoveManagedCoroutine(name)

        step = FSM.State(
            id=self.state_counter,
            name=f"Remove-{name}",
            execute_fn=_stopper,
            exit_condition=lambda: True,  # move on immediately
            run_once=True,
        )
        self._bind_state(step)

        if self.states:
            self.states[-1].set_next_state(step)

        self.states.append(step)
        self.state_counter += 1

    def RemoveAllManagedCoroutines(self) -> int:
        n = len(self.managed_coroutines)
        _retained = tuple(self.managed_coroutines) + tuple(self._named_managed.values())
        self._named_managed_attempts.clear()
        for binding in tuple(self._managed_dispatch_bindings.values()):
            self._detach_dispatch_binding(binding)
        self.managed_coroutines.clear()
        self._named_managed.clear()
        return n

    def HasManagedCoroutine(self, name: str) -> bool:
        gen = self._named_managed.get(name)
        if getattr(gen, "_fsm_dispatch_receipt", False):
            binding = self._managed_dispatch_bindings.get(id(gen))
            return binding is not None and self._dispatch_binding_is_current(*binding)
        return bool(gen and gen in self.managed_coroutines)

    def AdoptGlobalCoroutine(self, routine: Any, remove_from_global: bool = True) -> bool:
        from ..GlobalCache import GLOBAL_CACHE

        """
        Move (or copy) a generator from GLOBAL_CACHE.Coroutines into FSM-managed list.
        """
        if routine is None:
            return False
        if getattr(routine, "_fsm_dispatch_receipt", False):
            try:
                added = self._add_managed(routine)
            except Exception:
                self._discard_factory_result(routine)
                raise
            if not added:
                self._discard_factory_result(routine)
                return False
            binding = self._managed_dispatch_bindings.get(id(routine))
            try:
                if remove_from_global:
                    global_routines = cast(list[Iterator[Any]], getattr(GLOBAL_CACHE, "Coroutines"))
                    for index, item in enumerate(global_routines):
                        if item is routine:
                            del global_routines[index]
                            break
                return True
            except Exception:
                if binding is not None:
                    self._detach_dispatch_binding(binding)
                self._discard_factory_result(routine)
                raise
        if remove_from_global:
            try:
                GLOBAL_CACHE.Coroutines.remove(routine)
            except ValueError:
                pass
        return self._add_managed(routine)


#endregion
