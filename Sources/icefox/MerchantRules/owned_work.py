"""Per-widget leases and iterator lifetime for accepted Merchant Rules work."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from typing import Protocol
from typing import Self
from typing import cast

type Producer = Iterator[object]
type Action = Callable[..., object]
type QueueMethod = Literal["AddAction", "AddActionWithDelay"]
type Capture = tuple[object, list[tuple[QueueMethod, bool, object]]]
type Validity = Callable[[int], bool]
OWNED_ACTION_QUEUES = frozenset({"ACTION", "IDENTIFY", "SALVAGE"})


class CompletionField(StrEnum):
    ICON_XUNLAI_OPEN_RUNNING = "icon_xunlai_open_running"
    INVENTORY_SHORTCUTS_LIVE_ACTION_RUNNING = "inventory_shortcuts_live_action_running"
    IDENTIFY_RUNNING = "identify_running"
    INSTANT_DESTROY_RUNNING = "instant_destroy_running"
    SALVAGE_RUNNING = "salvage_running"
    EXECUTION_RUNNING = "execution_running"
    STORAGE_SCAN_RUNNING = "storage_scan_running"
    AUTO_CLEANUP_RUNNING = "auto_cleanup_running"
    GOLD_BALANCE_RUNNING = "gold_balance_running"
    MANUAL_VENDOR_RUNNING = "manual_vendor_running"
    IDENTIFY_RESCAN_REQUESTED = "identify_rescan_requested"
    SALVAGE_RESCAN_REQUESTED = "salvage_rescan_requested"
    INSTANT_DESTROY_RESCAN_REQUESTED = "instant_destroy_rescan_requested"
    AUTO_CLEANUP_ZONE_ATTEMPTED = "auto_cleanup_zone_attempted"
    AUTO_CLEANUP_ZONE_TOKEN = "auto_cleanup_zone_token"
    MANUAL_VENDOR_HANDLED_SIGNATURE = "manual_vendor_handled_signature"


_RESCAN_FIELDS = frozenset(
    {
        CompletionField.IDENTIFY_RESCAN_REQUESTED,
        CompletionField.SALVAGE_RESCAN_REQUESTED,
        CompletionField.INSTANT_DESTROY_RESCAN_REQUESTED,
    }
)


@dataclass(frozen=True, slots=True)
class Completion:
    flags: tuple[CompletionField, ...] = ()
    values: tuple[tuple[CompletionField, object], ...] = ()


class WorkRuntime(Protocol):
    """Live inputs and boundary effects. Construction must not observe any of them."""

    @property
    def profile_generation(self) -> int: ...

    @property
    def lifecycle_generation(self) -> int: ...

    @property
    def initialized(self) -> bool: ...

    @property
    def accepted_account(self) -> str: ...

    def observe_account(self) -> str: ...

    def refresh_lifecycle(self) -> int: ...

    def readiness_reason(self) -> str: ...

    def wait_for_lifecycle(self, expected: int) -> Generator[object, None, int | None]: ...

    def queue_manager(self) -> object: ...

    @property
    def owned_queues(self) -> frozenset[str]: ...

    def mark_action_source(self) -> None: ...

    def publish_completion(self, field: CompletionField, value: object) -> None: ...

    @property
    def generator_class(self) -> type[OwnedGenerator]: ...

    @property
    def callback_class(self) -> type[OwnedQueueCallback]: ...

    @property
    def work_release(self) -> Callable[[], None]: ...

    @property
    def action_release(self) -> Callable[[], None]: ...

    @property
    def dispatch_release(self) -> Callable[[], None]: ...

    @property
    def profile_validity(self) -> Validity: ...

    @property
    def lifecycle_validity(self) -> Validity: ...


class _MerchantRulesOwnedQueueCallback:
    """Track one Merchant Rules callback until it runs or is discarded."""

    __slots__ = (
        "_callback",
        "_pending",
        "_release",
        "_generation",
        "_is_generation_current",
        "_lifecycle_generation",
        "_is_lifecycle_current",
        "__name__",
    )

    def __init__(
        self,
        callback: Action,
        release: Callable[[], None],
        *,
        generation: int | None = None,
        is_generation_current: Callable[[int], bool] | None = None,
        lifecycle_generation: int | None = None,
        is_lifecycle_current: Callable[[int], bool] | None = None,
    ) -> None:
        self._callback = callback
        self._release: Callable[[], None] | None = release
        self._pending = True
        self._generation = generation
        self._is_generation_current = is_generation_current
        self._lifecycle_generation = lifecycle_generation
        self._is_lifecycle_current = is_lifecycle_current
        self.__name__ = str(getattr(callback, "__name__", callback.__class__.__name__))

    def release(self) -> None:
        if not self._pending:
            return
        self._pending = False
        release = self._release
        self._release = None
        if callable(release):
            release()

    def __call__(self, *args: object, **kwargs: object) -> object:
        if (
            self._generation is not None
            and callable(self._is_generation_current)
            and not self._is_generation_current(self._generation)
        ):
            self.release()
            return None
        if (
            self._lifecycle_generation is not None
            and callable(self._is_lifecycle_current)
            and not self._is_lifecycle_current(self._lifecycle_generation)
        ):
            self.release()
            return None
        try:
            return self._callback(*args, **kwargs)
        finally:
            self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class _MerchantRulesOwnedGenerator:
    """Iterator with explicit close-time release for one Merchant Rules operation."""

    __slots__ = (
        "_owner",
        "_generator",
        "_generation",
        "_release",
        "_capture_actions",
        "_reset_flags",
        "_reset_values_before_start",
        "_lifecycle_generation",
        "_lifecycle_wait_generator",
        "_allow_initial_lifecycle_transition",
        "_pending_initial_lifecycle_transition_generation",
        "_started",
        "_finished",
    )

    def __init__(
        self,
        owner: OwnedWorkSession,
        generator: Iterator[object],
        generation: int,
        release: Callable[[], None],
        *,
        capture_actions: bool,
        lifecycle_generation: int | None = None,
        allow_initial_lifecycle_transition: bool = False,
        completion: Callable[[], Completion] = Completion,
    ) -> None:
        self._owner = owner
        self._generator = generator
        self._generation = int(generation)
        self._release: Callable[[], None] | None = release
        self._capture_actions = bool(capture_actions)
        self._lifecycle_generation = int(lifecycle_generation) if lifecycle_generation is not None else None
        self._lifecycle_wait_generator: Generator[object, None, int | None] | None = None
        self._allow_initial_lifecycle_transition = bool(allow_initial_lifecycle_transition)
        self._pending_initial_lifecycle_transition_generation: int | None = None
        plan = completion()
        self._reset_flags = plan.flags
        self._reset_values_before_start = plan.values
        self._started = False
        self._finished = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> object:
        if self._finished:
            raise StopIteration
        if not self._owner.runtime.profile_validity(self._generation):
            self.close()
            raise StopIteration

        if self._lifecycle_generation is not None:
            while not self._owner.planned_travel_active:
                lifecycle_state = self._owner.lifecycle_state(
                    self._lifecycle_generation,
                )
                if lifecycle_state == "stale":
                    if (
                        self._allow_initial_lifecycle_transition
                        and self._pending_initial_lifecycle_transition_generation is None
                    ):
                        lifecycle_wait_generator = self._lifecycle_wait_generator
                        self._lifecycle_wait_generator = None
                        if lifecycle_wait_generator is not None:
                            close_wait = getattr(lifecycle_wait_generator, "close", None)
                            if callable(close_wait):
                                close_wait()
                        self._lifecycle_generation = int(self._owner.runtime.lifecycle_generation)
                        self._pending_initial_lifecycle_transition_generation = self._lifecycle_generation
                        continue
                    self.close()
                    raise StopIteration
                if lifecycle_state == "ready":
                    self._allow_initial_lifecycle_transition = False
                    self._pending_initial_lifecycle_transition_generation = None
                    break
                if self._lifecycle_wait_generator is None:
                    self._lifecycle_wait_generator = self._owner.runtime.wait_for_lifecycle(
                        self._lifecycle_generation,
                    )
                try:
                    return next(self._lifecycle_wait_generator)
                except StopIteration as stop:
                    self._lifecycle_wait_generator = None
                    if stop.value is None:
                        self.close()
                        raise StopIteration
                    self._lifecycle_generation = int(stop.value)

        self._started = True
        previous_lifecycle_generation = self._owner.active_lifecycle_generation
        self._owner.active_lifecycle_generation = self._lifecycle_generation
        try:
            if self._capture_actions:
                yielded_value = self._owner.advance(
                    self._generator,
                    self._generation,
                    lifecycle_generation=self._lifecycle_generation,
                )
            else:
                previous_generation = self._owner.active_generation
                self._owner.active_generation = self._generation
                try:
                    yielded_value = next(self._generator)
                finally:
                    self._owner.active_generation = previous_generation
        except StopIteration as stop:
            self._finish()
            raise stop
        except BaseException:
            self.close()
            raise
        finally:
            self._owner.active_lifecycle_generation = previous_lifecycle_generation

        if not self._owner.runtime.profile_validity(self._generation):
            self.close()
            raise StopIteration
        accepted_lifecycle_generation = self._owner.planned_lifecycle_generation
        if accepted_lifecycle_generation is not None:
            self._lifecycle_generation = int(accepted_lifecycle_generation)
            self._owner.planned_lifecycle_generation = None
        if (
            self._lifecycle_generation is not None
            and not self._owner.planned_travel_active
            and not self._owner.runtime.lifecycle_validity(self._lifecycle_generation)
        ):
            self.close()
            raise StopIteration
        return yielded_value

    def close(self) -> None:
        if self._finished:
            return
        try:
            if self._started:
                self._owner.close_started(
                    self._generator,
                    self._generation,
                    capture_actions=self._capture_actions,
                    lifecycle_generation=self._lifecycle_generation,
                )
            else:
                close = getattr(self._generator, "close", None)
                if callable(close):
                    close()
        finally:
            self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        release = self._release
        self._release = None
        try:
            if callable(release):
                release()
        finally:
            owner = self._owner
            reset_flags = self._reset_flags
            self._reset_flags = ()
            for flag_name in reset_flags:
                try:
                    owner.runtime.publish_completion(flag_name, False)
                except Exception:
                    pass
            reset_values = self._reset_values_before_start
            self._reset_values_before_start = ()
            if not self._started and reset_values:
                should_restore_rescan = True
                if any(field_name in _RESCAN_FIELDS for field_name, _value in reset_values):
                    try:
                        should_restore_rescan = int(owner.runtime.profile_generation) == self._generation
                        if should_restore_rescan and self._lifecycle_generation is not None:
                            lifecycle_generation = int(owner.runtime.lifecycle_generation)
                            if lifecycle_generation != self._lifecycle_generation:
                                should_restore_rescan = bool(
                                    self._allow_initial_lifecycle_transition
                                    and self._pending_initial_lifecycle_transition_generation is None
                                )
                    except Exception:
                        should_restore_rescan = False
                for field_name, value in reset_values:
                    if field_name in _RESCAN_FIELDS and not should_restore_rescan:
                        continue
                    try:
                        owner.runtime.publish_completion(field_name, value)
                    except Exception:
                        pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


OwnedGenerator = _MerchantRulesOwnedGenerator
OwnedQueueCallback = _MerchantRulesOwnedQueueCallback


class OwnedWorkSession:
    """Keep accepted work tied to the widget that admitted it across world transitions."""

    def __init__(self, runtime: WorkRuntime) -> None:
        self.runtime = runtime
        self.work_count = 0
        self.action_count = 0
        self.dispatch_count = 0
        self.active_generation: int | None = None
        self.active_lifecycle_generation: int | None = None
        self.planned_travel_active = False
        self.planned_lifecycle_generation: int | None = None

    def profile_is_current(self, generation: int | None = None) -> bool:
        if generation is None:
            generation = self.active_generation
        if generation is not None and int(generation) != int(self.runtime.profile_generation):
            return False
        if self.runtime.initialized and str(self.runtime.accepted_account or "").strip():
            try:
                current_account = self.runtime.observe_account()
                if current_account and current_account != self.runtime.accepted_account:
                    return False
            except Exception:
                return False
        return True

    def lifecycle_is_current(self, generation: int | None = None) -> bool:
        current = self.runtime.refresh_lifecycle()
        if generation is not None and int(generation) != current:
            return False
        return not self.runtime.readiness_reason()

    def lifecycle_state(self, generation: int) -> Literal["stale", "ready", "waiting"]:
        current = self.runtime.refresh_lifecycle()
        if int(generation) != current:
            return "stale"
        return "ready" if not self.runtime.readiness_reason() else "waiting"

    def operation_generation(self) -> int:
        if self.active_generation is not None:
            return int(self.active_generation)
        return int(self.runtime.profile_generation)

    def operation_lifecycle_generation(self) -> int:
        if self.active_lifecycle_generation is not None:
            return int(self.active_lifecycle_generation)
        return int(self.runtime.lifecycle_generation)

    def release_work(self) -> None:
        self.work_count = max(0, int(self.work_count) - 1)

    def release_action(self) -> None:
        self.action_count = max(0, int(self.action_count) - 1)

    def release_dispatch(self) -> None:
        self.dispatch_count = max(0, int(self.dispatch_count) - 1)

    def track_action(
        self, callback: Action, *, generation: int | None = None, lifecycle_generation: int | None = None
    ) -> OwnedQueueCallback:
        self.runtime.mark_action_source()
        self.action_count = max(0, int(self.action_count)) + 1
        try:
            profile = self.operation_generation() if generation is None else int(generation)
            lifecycle = (
                self.operation_lifecycle_generation() if lifecycle_generation is None else int(lifecycle_generation)
            )
            return self.runtime.callback_class(
                callback,
                self.runtime.action_release,
                generation=profile,
                is_generation_current=self.runtime.profile_validity,
                lifecycle_generation=lifecycle,
                is_lifecycle_current=self.runtime.lifecycle_validity,
            )
        except BaseException:
            self.runtime.action_release()
            raise

    def begin_capture(self, generation: int | None = None) -> Capture | None:
        """Capture only Merchant Rules action submissions made during one generator tick."""

        try:
            manager = self.runtime.queue_manager()
        except Exception:
            return None

        captures: list[tuple[QueueMethod, bool, object]] = []
        manager_attributes = cast(Mapping[str, object], getattr(manager, "__dict__", {}))

        def install_capture(method_name: QueueMethod, *, delayed: bool = False) -> None:
            original = cast(Action | None, getattr(manager, method_name, None))
            if not callable(original):
                return
            had_instance_override = bool(method_name in manager_attributes)
            previous_instance_value = manager_attributes.get(method_name)

            if delayed:

                def captured_delayed(
                    queue_name: object, delay: object, callback: Action, *args: object, **kwargs: object
                ) -> object:
                    if str(queue_name or "").upper() not in self.runtime.owned_queues:
                        return original(queue_name, delay, callback, *args, **kwargs)
                    owned_callback = self.track_action(
                        callback,
                        generation=generation,
                        lifecycle_generation=self.operation_lifecycle_generation(),
                    )
                    try:
                        return original(queue_name, delay, owned_callback, *args, **kwargs)
                    except BaseException:
                        owned_callback.release()
                        raise

                captured = captured_delayed
            else:

                def captured_immediate(queue_name: object, callback: Action, *args: object, **kwargs: object) -> object:
                    if str(queue_name or "").upper() not in self.runtime.owned_queues:
                        return original(queue_name, callback, *args, **kwargs)
                    owned_callback = self.track_action(
                        callback,
                        generation=generation,
                        lifecycle_generation=self.operation_lifecycle_generation(),
                    )
                    try:
                        return original(queue_name, owned_callback, *args, **kwargs)
                    except BaseException:
                        owned_callback.release()
                        raise

                captured = captured_immediate

            try:
                setattr(manager, method_name, captured)
            except Exception:
                return
            captures.append((method_name, had_instance_override, previous_instance_value))

        install_capture("AddAction")
        install_capture("AddActionWithDelay", delayed=True)
        return manager, captures

    @staticmethod
    def end_capture(capture: Capture | None) -> None:
        if capture is None:
            return
        manager, captures = capture
        for method_name, had_instance_override, previous_instance_value in reversed(captures):
            try:
                if had_instance_override:
                    setattr(manager, method_name, previous_instance_value)
                else:
                    delattr(manager, method_name)
            except Exception:
                pass

    def close_started(
        self,
        generator: Iterator[object],
        generation: int | None = None,
        *,
        capture_actions: bool = True,
        lifecycle_generation: int | None = None,
    ) -> None:
        close = getattr(generator, "close", None)
        if not callable(close):
            return
        previous_generation = self.active_generation
        previous_lifecycle_generation = self.active_lifecycle_generation
        self.active_generation = generation
        self.active_lifecycle_generation = lifecycle_generation
        capture = self.begin_capture(generation) if capture_actions else None
        try:
            close()
        except RuntimeError:
            pass
        finally:
            self.end_capture(capture)
            self.active_generation = previous_generation
            self.active_lifecycle_generation = previous_lifecycle_generation

    def advance(
        self,
        generator: Iterator[object],
        generation: int,
        *,
        lifecycle_generation: int | None = None,
    ) -> object:
        previous_generation = self.active_generation
        previous_lifecycle_generation = self.active_lifecycle_generation
        self.active_generation = generation
        self.active_lifecycle_generation = lifecycle_generation
        capture = self.begin_capture(generation)
        try:
            return next(generator)
        finally:
            self.end_capture(capture)
            self.active_generation = previous_generation
            self.active_lifecycle_generation = previous_lifecycle_generation

    @staticmethod
    def _discard_failed_generator(generator: Iterator[object]) -> None:
        close = getattr(generator, "close", None)
        if callable(close):
            try:
                close()
            except BaseException:
                pass

    def track_work(
        self,
        generator: Iterator[object],
        generation: int,
        lifecycle_generation: int,
        allow_initial_transition: bool,
        completion: Callable[[], Completion],
    ) -> OwnedGenerator:
        self.work_count = max(0, int(self.work_count)) + 1
        try:
            return self.runtime.generator_class(
                self,
                generator,
                generation,
                self.runtime.work_release,
                capture_actions=True,
                lifecycle_generation=lifecycle_generation,
                allow_initial_lifecycle_transition=allow_initial_transition,
                completion=completion,
            )
        except BaseException:
            self._discard_failed_generator(generator)
            self.runtime.work_release()
            raise

    def track_dispatch(
        self,
        generator: Iterator[object],
        generation: int,
        lifecycle_generation: int,
        allow_initial_transition: bool,
    ) -> OwnedGenerator:
        self.dispatch_count = max(0, int(self.dispatch_count)) + 1
        try:
            return self.runtime.generator_class(
                self,
                generator,
                generation,
                self.runtime.dispatch_release,
                capture_actions=False,
                lifecycle_generation=lifecycle_generation,
                allow_initial_lifecycle_transition=allow_initial_transition,
            )
        except BaseException:
            self._discard_failed_generator(generator)
            self.runtime.dispatch_release()
            raise

    def track_reload(self, generator: Iterator[object], generation: int, release: Callable[[], None]) -> OwnedGenerator:
        try:
            return self.runtime.generator_class(self, generator, generation, release, capture_actions=False)
        except BaseException:
            release()
            self._discard_failed_generator(generator)
            raise
